//! STB-Core v0.2 – Release Candidate Final (Consensus Total)
//!
//! - ✅ Overflow usize → u32 / u16 eliminado com `try_from`
//! - ✅ Limite de saída (64 MB) protege contra OOM
//! - ✅ Limite de iterações de loop (1.000.000) protege contra DoS
//! - ✅ Validação SHA256 no carregamento da biblioteca de genes
//! - ✅ Nenhuma variante de erro morta – `VmError` apenas erros de VM
//! - ✅ Testes de segurança incluídos

use std::collections::HashMap;
use std::fs;
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, RwLock};
use sha2::{Sha256, Digest};

#[cfg(feature = "zstd")]
use zstd::stream::{encode_all, decode_all};

// ============================================================================
// L1 – Purificação (Ψ e classificação)
// ============================================================================

#[derive(Debug, Clone, Copy)]
pub struct PurificationWeights {
    pub alpha: f64,
    pub beta: f64,
    pub delta: f64,
    pub gamma: f64,
}

impl Default for PurificationWeights {
    fn default() -> Self {
        Self {
            alpha: 0.4,
            beta: 0.3,
            delta: 0.2,
            gamma: 0.1,
        }
    }
}

#[derive(Debug, Clone, Copy)]
pub struct PurificationThresholds {
    pub structural: f64,
    pub residual: f64,
}

impl Default for PurificationThresholds {
    fn default() -> Self {
        Self {
            structural: 0.7,
            residual: 0.3,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SegmentClass {
    Structural,
    Substitutable,
    Residual,
}

pub fn shannon_entropy(data: &[u8]) -> f64 {
    if data.is_empty() {
        return 0.0;
    }
    let mut freq = [0; 256];
    for &b in data {
        freq[b as usize] += 1;
    }
    let len = data.len() as f64;
    freq.iter()
        .filter(|&&c| c > 0)
        .map(|&c| {
            let p = c as f64 / len;
            -p * p.log2()
        })
        .sum()
}

pub fn psi_score(freq: f64, pred: f64, reuse: f64, compl: f64, w: &PurificationWeights) -> f64 {
    w.alpha * freq + w.beta * pred + w.delta * reuse - w.gamma * compl
}

pub fn classify(psi: f64, th: &PurificationThresholds) -> SegmentClass {
    if psi > th.structural {
        SegmentClass::Structural
    } else if psi > th.residual {
        SegmentClass::Substitutable
    } else {
        SegmentClass::Residual
    }
}

// ============================================================================
// L2 – Gene Library (persistente, evolutiva, concorrente)
// ============================================================================

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct Gene {
    pub id: String,
    pub signature: [u8; 32],
    pub payload: Vec<u8>,
    #[serde(skip)]
    pub hits: Arc<AtomicU64>,
    pub hits_saved: u64,
    pub saved_entropy: f64,
    pub storage_cost: f64,
    pub compute_cost: f64,
}

impl Gene {
    pub fn new(id: String, payload: Vec<u8>) -> Self {
        let signature = {
            let mut hasher = Sha256::new();
            hasher.update(&payload);
            hasher.finalize().into()
        };
        Self {
            id,
            signature,
            payload: payload.clone(),
            hits: Arc::new(AtomicU64::new(0)),
            hits_saved: 0,
            saved_entropy: 8.0 - shannon_entropy(&payload),
            storage_cost: payload.len() as f64,
            compute_cost: 1.0,
        }
    }

    pub fn fitness(&self, lambda: (f64, f64, f64, f64)) -> f64 {
        let (l1, l2, l3, l4) = lambda;
        let usage = self.hits.load(Ordering::Relaxed) as f64;
        l1 * usage + l2 * self.saved_entropy - l3 * self.storage_cost - l4 * self.compute_cost
    }

    pub fn amortized_cost(&self) -> f64 {
        let k = self.hits.load(Ordering::Relaxed) as f64;
        if k == 0.0 {
            self.storage_cost
        } else {
            self.storage_cost / k
        }
    }

    pub fn record_use(&self) {
        self.hits.fetch_add(1, Ordering::Relaxed);
    }

    pub fn freeze(&mut self) {
        self.hits_saved = self.hits.load(Ordering::Relaxed);
    }

    pub fn thaw(&mut self) {
        self.hits = Arc::new(AtomicU64::new(self.hits_saved));
    }
}

#[derive(Clone)]
pub struct GeneLibrary {
    inner: Arc<RwLock<HashMap<String, Gene>>>,
    path: Option<PathBuf>,
}

impl GeneLibrary {
    pub fn new() -> Self {
        Self {
            inner: Arc::new(RwLock::new(HashMap::new())),
            path: None,
        }
    }

    pub fn load(path: &std::path::Path) -> Result<Self, Box<dyn std::error::Error>> {
        let data = fs::read(path)?;
        let mut genes: HashMap<String, Gene> = bincode::deserialize(&data)?;

        for gene in genes.values_mut() {
            // Verifica integridade da assinatura
            let mut hasher = Sha256::new();
            hasher.update(&gene.payload);
            let computed: [u8; 32] = hasher.finalize().into();
            if computed != gene.signature {
                return Err(format!("Gene '{}' signature mismatch", gene.id).into());
            }
            gene.thaw();
        }

        Ok(Self {
            inner: Arc::new(RwLock::new(genes)),
            path: Some(path.to_path_buf()),
        })
    }

    pub fn save(&self) -> Result<(), Box<dyn std::error::Error>> {
        if let Some(p) = &self.path {
            let mut snapshot = self.inner.read().unwrap().clone();
            for gene in snapshot.values_mut() {
                gene.freeze();
            }
            let data = bincode::serialize(&snapshot)?;
            fs::write(p, data)?;
        }
        Ok(())
    }

    pub fn insert(&self, mut gene: Gene) {
        gene.thaw();
        self.inner.write().unwrap().insert(gene.id.clone(), gene);
    }

    pub fn get(&self, id: &str) -> Option<Gene> {
        self.inner.read().unwrap().get(id).cloned()
    }

    pub fn prune(&self, threshold: f64, lambda: (f64, f64, f64, f64)) {
        self.inner
            .write()
            .unwrap()
            .retain(|_, g| g.fitness(lambda) >= threshold);
    }
}

impl Default for GeneLibrary {
    fn default() -> Self {
        Self::new()
    }
}

// ============================================================================
// L3 – AST tipada (Seq é flatten no compile)
// ============================================================================

#[derive(Debug, Clone)]
pub enum Instruction {
    Def { id: String, data: Vec<u8> },
    Ref { id: String },
    Rpt { count: usize, body: Box<Instruction> },
    Seq(Vec<Instruction>),
    Ale { seed: u64, len: usize },
    Err(String),
    Stp,
}

// ============================================================================
// L4 – Bytecode binário (sem Seq/SeqEnd)
// ============================================================================

#[repr(u8)]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Opcode {
    Def = 0x01,
    Ref = 0x02,
    Rpt = 0x03,
    RptEnd = 0x04,
    Ale = 0x07,
    Err = 0x08,
    Stp = 0xFF,
}

#[derive(Debug, Clone)]
pub struct BytecodeProgram {
    pub bytes: Vec<u8>,
}

pub struct Compiler;

impl Compiler {
    /// Compila uma AST em bytecode. Retorna erro se count/len ou tamanhos de string excederem limites.
    pub fn compile(ast: &Instruction) -> Result<BytecodeProgram, VmError> {
        let mut bytes = Vec::new();
        Self::compile_instr(ast, &mut bytes)?;
        Ok(BytecodeProgram { bytes })
    }

    fn compile_instr(instr: &Instruction, out: &mut Vec<u8>) -> Result<(), VmError> {
        match instr {
            Instruction::Def { id, data } => {
                out.push(Opcode::Def as u8);
                let id_bytes = id.as_bytes();
                let id_len = u16::try_from(id_bytes.len())
                    .map_err(|_| VmError::Custom("Gene id too long (>65535)".into()))?;
                out.extend_from_slice(&id_len.to_le_bytes());
                out.extend_from_slice(id_bytes);
                let data_len = u32::try_from(data.len())
                    .map_err(|_| VmError::Custom("Gene data too large (>4GB)".into()))?;
                out.extend_from_slice(&data_len.to_le_bytes());
                out.extend_from_slice(data);
            }
            Instruction::Ref { id } => {
                out.push(Opcode::Ref as u8);
                let id_bytes = id.as_bytes();
                let id_len = u16::try_from(id_bytes.len())
                    .map_err(|_| VmError::Custom("Gene id too long (>65535)".into()))?;
                out.extend_from_slice(&id_len.to_le_bytes());
                out.extend_from_slice(id_bytes);
            }
            Instruction::Rpt { count, body } => {
                out.push(Opcode::Rpt as u8);
                let count_u32 = u32::try_from(*count)
                    .map_err(|_| VmError::Custom("Rpt count exceeds u32 range".into()))?;
                out.extend_from_slice(&count_u32.to_le_bytes());
                Self::compile_instr(body, out)?;
                out.push(Opcode::RptEnd as u8);
            }
            Instruction::Seq(list) => {
                for sub in list {
                    Self::compile_instr(sub, out)?;
                }
            }
            Instruction::Ale { seed, len } => {
                out.push(Opcode::Ale as u8);
                out.extend_from_slice(&seed.to_le_bytes());
                let len_u32 = u32::try_from(*len)
                    .map_err(|_| VmError::Custom("Ale length exceeds u32 range".into()))?;
                out.extend_from_slice(&len_u32.to_le_bytes());
            }
            Instruction::Err(msg) => {
                out.push(Opcode::Err as u8);
                let msg_bytes = msg.as_bytes();
                let msg_len = u16::try_from(msg_bytes.len())
                    .map_err(|_| VmError::Custom("Error message too long (>65535)".into()))?;
                out.extend_from_slice(&msg_len.to_le_bytes());
                out.extend_from_slice(msg_bytes);
            }
            Instruction::Stp => {
                out.push(Opcode::Stp as u8);
            }
        }
        Ok(())
    }
}

// ============================================================================
// Capsídeo Digital (SHA256 do bytecode)
// ============================================================================

#[derive(Debug, Clone)]
pub enum TolerancePolicy {
    Exact,
    Perceptual,
    Semantic,
}

#[derive(Debug, Clone)]
pub enum FallbackPolicy {
    Classical,
    Abort,
    Partial,
}

#[derive(Debug, Clone)]
pub struct Capsid {
    pub domain: String,
    pub lookup_version: String,
    pub entry_point: String,
    pub bytecode_checksum: [u8; 32],
    pub tolerance: TolerancePolicy,
    pub fallback: FallbackPolicy,
    pub metadata: HashMap<String, String>,
}

impl Capsid {
    pub fn from_bytecode(domain: &str, bytecode: &BytecodeProgram) -> Self {
        let checksum = Self::compute_checksum(&bytecode.bytes);
        Self {
            domain: domain.to_string(),
            lookup_version: env!("CARGO_PKG_VERSION").to_string(),
            entry_point: "main".to_string(),
            bytecode_checksum: checksum,
            tolerance: TolerancePolicy::Perceptual,
            fallback: FallbackPolicy::Classical,
            metadata: HashMap::new(),
        }
    }

    pub fn compute_checksum(data: &[u8]) -> [u8; 32] {
        let mut hasher = Sha256::new();
        hasher.update(data);
        hasher.finalize().into()
    }
}

pub struct TransmissionUnit {
    pub capsid: Capsid,
    pub used_genes: Vec<Gene>,
    pub bytecode: BytecodeProgram,
    pub compressed_residual: Vec<u8>,
}

// ============================================================================
// L5 – STB Virtual Machine (com todos os limites)
// ============================================================================

const MAX_OUTPUT_SIZE: usize = 64 * 1024 * 1024; // 64 MB
const MAX_LOOP_COUNT: u32 = 1_000_000; // 1 milhão de iterações

#[derive(Debug, PartialEq)]
pub enum VmError {
    OutOfBounds,
    InvalidOpcode(u8),
    GeneNotFound(String),
    LoopMismatch,
    Apoptosis(String),
    Custom(String),
}

pub struct STBVM {
    library: GeneLibrary,
    locals: HashMap<String, Vec<u8>>,
    output: Vec<u8>,
    pub trace: Vec<String>,
    executed_instr: usize,
    failed_genes: usize,
    loop_stack: Vec<(usize, u32)>, // (pc_return, remaining_iterations)
    permissive_mode: bool,
}

impl STBVM {
    pub fn new(library: GeneLibrary) -> Self {
        Self::new_with_mode(library, false)
    }

    pub fn new_with_mode(library: GeneLibrary, permissive: bool) -> Self {
        Self {
            library,
            locals: HashMap::new(),
            output: Vec::new(),
            trace: Vec::new(),
            executed_instr: 0,
            failed_genes: 0,
            loop_stack: Vec::new(),
            permissive_mode: permissive,
        }
    }

    // === Helpers de leitura segura ===
    fn read_u16(bytes: &[u8], pc: &mut usize) -> Result<u16, VmError> {
        if *pc + 1 >= bytes.len() {
            return Err(VmError::OutOfBounds);
        }
        let v = u16::from_le_bytes([bytes[*pc], bytes[*pc + 1]]);
        *pc += 2;
        Ok(v)
    }

    fn read_u32(bytes: &[u8], pc: &mut usize) -> Result<u32, VmError> {
        if *pc + 3 >= bytes.len() {
            return Err(VmError::OutOfBounds);
        }
        let v = u32::from_le_bytes([bytes[*pc], bytes[*pc + 1], bytes[*pc + 2], bytes[*pc + 3]]);
        *pc += 4;
        Ok(v)
    }

    fn read_u64(bytes: &[u8], pc: &mut usize) -> Result<u64, VmError> {
        if *pc + 7 >= bytes.len() {
            return Err(VmError::OutOfBounds);
        }
        let v = u64::from_le_bytes(bytes[*pc..*pc + 8].try_into().unwrap());
        *pc += 8;
        Ok(v)
    }

    fn read_string(bytes: &[u8], pc: &mut usize) -> Result<String, VmError> {
        let len = Self::read_u16(bytes, pc)? as usize;
        if *pc + len > bytes.len() {
            return Err(VmError::OutOfBounds);
        }
        let s = String::from_utf8_lossy(&bytes[*pc..*pc + len]).to_string();
        *pc += len;
        Ok(s)
    }

    fn read_bytes(bytes: &[u8], pc: &mut usize) -> Result<Vec<u8>, VmError> {
        let len = Self::read_u32(bytes, pc)? as usize;
        if *pc + len > bytes.len() {
            return Err(VmError::OutOfBounds);
        }
        let data = bytes[*pc..*pc + len].to_vec();
        *pc += len;
        Ok(data)
    }

    fn append_output(&mut self, data: &[u8]) -> Result<(), VmError> {
        if self.output.len().saturating_add(data.len()) > MAX_OUTPUT_SIZE {
            return Err(VmError::Custom("Output size limit exceeded".into()));
        }
        self.output.extend_from_slice(data);
        Ok(())
    }

    fn skip_instruction(&self, bytes: &[u8], pc: &mut usize) -> Result<(), VmError> {
        if *pc >= bytes.len() {
            return Err(VmError::OutOfBounds);
        }
        let op = bytes[*pc];
        *pc += 1;
        match op {
            x if x == Opcode::Def as u8 => {
                Self::read_string(bytes, pc)?;
                Self::read_bytes(bytes, pc)?;
            }
            x if x == Opcode::Ref as u8 => {
                Self::read_string(bytes, pc)?;
            }
            x if x == Opcode::Rpt as u8 => {
                Self::read_u32(bytes, pc)?;
                let mut depth = 1;
                while depth > 0 && *pc < bytes.len() {
                    match bytes[*pc] {
                        x if x == Opcode::Rpt as u8 => {
                            *pc += 1;
                            Self::read_u32(bytes, pc)?;
                            depth += 1;
                        }
                        x if x == Opcode::RptEnd as u8 => {
                            *pc += 1;
                            depth -= 1;
                        }
                        _ => self.skip_instruction(bytes, pc)?,
                    }
                }
                if depth != 0 {
                    return Err(VmError::LoopMismatch);
                }
            }
            x if x == Opcode::RptEnd as u8 => {}
            x if x == Opcode::Ale as u8 => {
                Self::read_u64(bytes, pc)?;
                Self::read_u32(bytes, pc)?;
            }
            x if x == Opcode::Err as u8 => {
                Self::read_string(bytes, pc)?;
            }
            x if x == Opcode::Stp as u8 => {}
            _ => return Err(VmError::InvalidOpcode(op)),
        }
        Ok(())
    }

    pub fn execute_bytecode(&mut self, bytecode: &BytecodeProgram) -> Result<Vec<u8>, VmError> {
        let mut pc = 0;
        let bytes = &bytecode.bytes;
        self.output.clear();
        self.failed_genes = 0;
        self.executed_instr = 0;
        self.trace.clear();
        self.loop_stack.clear();

        while pc < bytes.len() {
            let op = bytes[pc];
            pc += 1;
            self.executed_instr += 1;

            match op {
                x if x == Opcode::Def as u8 => {
                    let id = Self::read_string(bytes, &mut pc)?;
                    let data = Self::read_bytes(bytes, &mut pc)?;
                    self.locals.insert(id.clone(), data);
                    self.trace.push(format!("DEF {}", id));
                }
                x if x == Opcode::Ref as u8 => {
                    let id = Self::read_string(bytes, &mut pc)?;
                    let data = if let Some(local) = self.locals.get(&id) {
                        local.clone()
                    } else if let Some(gene) = self.library.get(&id) {
                        gene.record_use();
                        gene.payload.clone()
                    } else {
                        self.failed_genes += 1;
                        self.trace.push(format!("⚠️ MISS {}", id));
                        if !self.permissive_mode {
                            return Err(VmError::GeneNotFound(id));
                        }
                        vec![]
                    };
                    self.append_output(&data)?;
                    self.trace.push(format!("REF {} ({}b)", id, data.len()));
                }
                x if x == Opcode::Rpt as u8 => {
                    let count = Self::read_u32(bytes, &mut pc)?;
                    if count == 0 {
                        let mut depth = 1;
                        while depth > 0 && pc < bytes.len() {
                            match bytes[pc] {
                                x if x == Opcode::Rpt as u8 => {
                                    pc += 1;
                                    Self::read_u32(bytes, &mut pc)?;
                                    depth += 1;
                                }
                                x if x == Opcode::RptEnd as u8 => {
                                    pc += 1;
                                    depth -= 1;
                                }
                                _ => self.skip_instruction(bytes, &mut pc)?,
                            }
                        }
                        if depth != 0 {
                            return Err(VmError::LoopMismatch);
                        }
                    } else {
                        if count > MAX_LOOP_COUNT {
                            return Err(VmError::Custom(format!(
                                "Loop count {} exceeds limit {}",
                                count, MAX_LOOP_COUNT
                            )));
                        }
                        self.loop_stack.push((pc, count - 1));
                    }
                }
                x if x == Opcode::RptEnd as u8 => {
                    if let Some((start_pc, remaining)) = self.loop_stack.last_mut() {
                        if *remaining > 0 {
                            *remaining -= 1;
                            pc = *start_pc;
                        } else {
                            self.loop_stack.pop();
                        }
                    } else {
                        return Err(VmError::LoopMismatch);
                    }
                }
                x if x == Opcode::Ale as u8 => {
                    let seed = Self::read_u64(bytes, &mut pc)?;
                    let len = Self::read_u32(bytes, &mut pc)? as usize;
                    if len > MAX_OUTPUT_SIZE {
                        return Err(VmError::Custom("Ale length exceeds output limit".into()));
                    }
                    let mut x = seed;
                    let mut buf = Vec::with_capacity(len);
                    for _ in 0..len {
                        x ^= x << 13;
                        x ^= x >> 7;
                        x ^= x << 17;
                        buf.push((x & 0xFF) as u8);
                    }
                    self.append_output(&buf)?;
                    self.trace.push(format!("ALE seed={}", seed));
                }
                x if x == Opcode::Err as u8 => {
                    let msg = Self::read_string(bytes, &mut pc)?;
                    self.failed_genes += 1;
                    if !self.permissive_mode {
                        return Err(VmError::Custom(msg));
                    }
                    self.trace.push(format!("⚠️ ERR: {}", msg));
                }
                x if x == Opcode::Stp as u8 => {
                    self.trace.push("STP".to_string());
                    break;
                }
                _ => return Err(VmError::InvalidOpcode(op)),
            }
        }

        if self.permissive_mode
            && self.executed_instr > 0
            && (self.failed_genes as f64 / self.executed_instr as f64) > 0.5
        {
            return Err(VmError::Apoptosis(format!(
                "{}/{} genes falharam (>50%)",
                self.failed_genes, self.executed_instr
            )));
        }
        Ok(self.output.clone())
    }
}

// ============================================================================
// Transmissão (com checksum)
// ============================================================================

pub fn transmit(unit: TransmissionUnit, library: &GeneLibrary) -> Result<Vec<u8>, VmError> {
    let program_checksum = Capsid::compute_checksum(&unit.bytecode.bytes);
    if program_checksum != unit.capsid.bytecode_checksum {
        return match unit.capsid.fallback {
            FallbackPolicy::Classical => Err(VmError::Custom(
                "Checksum mismatch – fallback clássico".to_string(),
            )),
            FallbackPolicy::Abort => {
                Err(VmError::Custom("Checksum mismatch – abortado".to_string()))
            }
            FallbackPolicy::Partial => {
                eprintln!("⚠️ Checksum mismatch, executando mesmo assim (partial)");
                let mut vm = STBVM::new(library.clone());
                vm.execute_bytecode(&unit.bytecode)
            }
        };
    }
    let mut vm = STBVM::new(library.clone());
    vm.execute_bytecode(&unit.bytecode)
}

// ============================================================================
// Compressão residual (zstd opcional)
// ============================================================================

#[cfg(feature = "zstd")]
pub fn compress_residual(data: &[u8], level: i32) -> Vec<u8> {
    encode_all(data, level).unwrap_or_else(|_| data.to_vec())
}
#[cfg(feature = "zstd")]
pub fn decompress_residual(data: &[u8]) -> Vec<u8> {
    decode_all(data).unwrap_or_else(|_| data.to_vec())
}
#[cfg(not(feature = "zstd"))]
pub fn compress_residual(data: &[u8], _level: i32) -> Vec<u8> {
    data.to_vec()
}
#[cfg(not(feature = "zstd"))]
pub fn decompress_residual(data: &[u8]) -> Vec<u8> {
    data.to_vec()
}

// ============================================================================
// Métricas
// ============================================================================

pub fn compression_ratio(
    original_bytes: usize,
    program_bytes: usize,
    residual_bytes: usize,
    capsid_bytes: usize,
) -> f64 {
    let total = program_bytes + residual_bytes + capsid_bytes;
    if total == 0 {
        f64::INFINITY
    } else {
        original_bytes as f64 / total as f64
    }
}

pub fn structural_coefficient(original_entropy: f64, residual_entropy: f64) -> f64 {
    if original_entropy == 0.0 {
        1.0
    } else {
        1.0 - (residual_entropy / original_entropy)
    }
}

// ============================================================================
// Testes
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_def_ref() -> Result<(), VmError> {
        let ast = Instruction::Seq(vec![
            Instruction::Def {
                id: "g".to_string(),
                data: b"hello".to_vec(),
            },
            Instruction::Ref {
                id: "g".to_string(),
            },
            Instruction::Stp,
        ]);
        let bytecode = Compiler::compile(&ast)?;
        let mut vm = STBVM::new(GeneLibrary::new());
        let out = vm.execute_bytecode(&bytecode)?;
        assert_eq!(out, b"hello");
        Ok(())
    }

    #[test]
    fn test_rpt_loop() -> Result<(), VmError> {
        let ast = Instruction::Seq(vec![
            Instruction::Def {
                id: "x".to_string(),
                data: b"AB".to_vec(),
            },
            Instruction::Rpt {
                count: 3,
                body: Box::new(Instruction::Ref {
                    id: "x".to_string(),
                }),
            },
            Instruction::Stp,
        ]);
        let bytecode = Compiler::compile(&ast)?;
        let mut vm = STBVM::new(GeneLibrary::new());
        let out = vm.execute_bytecode(&bytecode)?;
        assert_eq!(out, b"ABABAB");
        Ok(())
    }

    #[test]
    fn test_rpt_zero() -> Result<(), VmError> {
        let ast = Instruction::Seq(vec![
            Instruction::Def {
                id: "x".to_string(),
                data: b"AB".to_vec(),
            },
            Instruction::Rpt {
                count: 0,
                body: Box::new(Instruction::Ref {
                    id: "x".to_string(),
                }),
            },
            Instruction::Stp,
        ]);
        let bytecode = Compiler::compile(&ast)?;
        let mut vm = STBVM::new(GeneLibrary::new());
        let out = vm.execute_bytecode(&bytecode)?;
        assert_eq!(out, b"");
        Ok(())
    }

    #[test]
    fn test_loop_count_limit() -> Result<(), VmError> {
        let ast = Instruction::Seq(vec![
            Instruction::Def {
                id: "a".to_string(),
                data: b"A".to_vec(),
            },
            Instruction::Rpt {
                count: (MAX_LOOP_COUNT as usize) + 1,
                body: Box::new(Instruction::Ref {
                    id: "a".to_string(),
                }),
            },
            Instruction::Stp,
        ]);
        let bytecode = Compiler::compile(&ast)?;
        let mut vm = STBVM::new(GeneLibrary::new());
        let result = vm.execute_bytecode(&bytecode);
        assert!(matches!(result, Err(VmError::Custom(_))));
        Ok(())
    }

    #[test]
    fn test_ale_too_large() -> Result<(), VmError> {
        let ast = Instruction::Seq(vec![
            Instruction::Ale {
                seed: 42,
                len: MAX_OUTPUT_SIZE + 1,
            },
            Instruction::Stp,
        ]);
        let bytecode = Compiler::compile(&ast)?;
        let mut vm = STBVM::new(GeneLibrary::new());
        let result = vm.execute_bytecode(&bytecode);
        assert!(matches!(result, Err(VmError::Custom(_))));
        Ok(())
    }

    #[test]
    fn test_capsid_checksum() -> Result<(), VmError> {
        let ast = Instruction::Seq(vec![
            Instruction::Def {
                id: "msg".to_string(),
                data: b"OK".to_vec(),
            },
            Instruction::Ref {
                id: "msg".to_string(),
            },
            Instruction::Stp,
        ]);
        let bytecode = Compiler::compile(&ast)?;
        let capsid = Capsid::from_bytecode("test", &bytecode);
        let unit = TransmissionUnit {
            capsid,
            used_genes: vec![],
            bytecode,
            compressed_residual: vec![],
        };
        let library = GeneLibrary::new();
        let output = transmit(unit, &library)?;
        assert_eq!(output, b"OK");
        Ok(())
    }

    #[test]
    fn test_truncated_bytecode_fails() {
        let bytecode = BytecodeProgram {
            bytes: vec![Opcode::Ref as u8, 0x01],
        };
        let mut vm = STBVM::new(GeneLibrary::new());
        let result = vm.execute_bytecode(&bytecode);
        assert!(matches!(result, Err(VmError::OutOfBounds)));
    }

    #[test]
    fn test_apoptose_permissive() -> Result<(), VmError> {
        let ast = Instruction::Seq(vec![
            Instruction::Ref {
                id: "missing".to_string(),
            },
            Instruction::Ref {
                id: "missing2".to_string(),
            },
            Instruction::Ref {
                id: "missing3".to_string(),
            },
            Instruction::Stp,
        ]);
        let bytecode = Compiler::compile(&ast)?;
        let mut vm = STBVM::new_with_mode(GeneLibrary::new(), true);
        let result = vm.execute_bytecode(&bytecode);
        assert!(matches!(result, Err(VmError::Apoptosis(_))));
        Ok(())
    }

    #[test]
    fn test_permissive_below_threshold() -> Result<(), VmError> {
        let ast = Instruction::Seq(vec![
            Instruction::Def {
                id: "ok".to_string(),
                data: b"X".to_vec(),
            },
            Instruction::Ref {
                id: "ok".to_string(),
            },
            Instruction::Ref {
                id: "missing".to_string(),
            },
            Instruction::Ref {
                id: "ok".to_string(),
            },
            Instruction::Stp,
        ]);
        let bytecode = Compiler::compile(&ast)?;
        let mut vm = STBVM::new_with_mode(GeneLibrary::new(), true);
        let out = vm.execute_bytecode(&bytecode)?;
        assert_eq!(out, b"XX");
        assert_eq!(vm.failed_genes, 1);
        Ok(())
    }

    #[test]
    fn test_apoptose_strict_mode() -> Result<(), VmError> {
        let ast = Instruction::Seq(vec![
            Instruction::Ref {
                id: "missing".to_string(),
            },
            Instruction::Stp,
        ]);
        let bytecode = Compiler::compile(&ast)?;
        let mut vm = STBVM::new(GeneLibrary::new());
        let result = vm.execute_bytecode(&bytecode);
        assert!(matches!(result, Err(VmError::GeneNotFound(_))));
        Ok(())
    }
}

fn main() -> Result<(), VmError> {
    println!("STB-Core v0.2 – Release Candidate (todas as correções aplicadas)");
    let ast = Instruction::Seq(vec![
        Instruction::Def {
            id: "greeting".to_string(),
            data: b"Hello STB! ".to_vec(),
        },
        Instruction::Rpt {
            count: 3,
            body: Box::new(Instruction::Ref {
                id: "greeting".to_string(),
            }),
        },
        Instruction::Ale { seed: 123, len: 2 },
        Instruction::Stp,
    ]);
    let bytecode = Compiler::compile(&ast)?;
    println!("Bytecode size: {} bytes", bytecode.bytes.len());
    let mut vm = STBVM::new(GeneLibrary::new());
    let out = vm.execute_bytecode(&bytecode)?;
    println!("Output: {:?}", String::from_utf8_lossy(&out));
    Ok(())
}
