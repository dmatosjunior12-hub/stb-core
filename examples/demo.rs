//! Demonstração do pipeline: definição, repetição, ALE e execução na VM.
//!
//! Executar: cargo run --example demo

use stb_core::{Compiler, GeneLibrary, Instruction, STBVM, VmError};

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
