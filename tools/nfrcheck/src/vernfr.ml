(* open Parser_lib.Ispec  *)
open DataflowChecker 
open ControlFlowChecker
(* open GenericNFRChecker *)
open Options
(* open Cil_types *)

(* let foo_vi = (Cil.emptyFunction "foo").svar
let bar_vi = (Cil.emptyFunction "bar").svar
let finit_vi = (Cil.emptyFunction "f_init").svar
let f10ms_vi = (Cil.emptyFunction "f_10ms").svar  
let test_entry = CalledBefore (finit_vi, f10ms_vi)

let test_restricted_include = {
  hfile = "mod.h";
  fns = [foo_vi; bar_vi];
}

let test_call_restrictions = {
  includes = [test_restricted_include];
  call_order = [];
} 

let test_spec = {
  entry_fns = [finit_vi; f10ms_vi];
  entry_order = [test_entry];
  extern_calls = test_call_restrictions;
}


 *)

let run () = 
  if Enabled.get () then
    let ispec_file = ISpecFile.get () in
    let ispec = if (ispec_file = "") then 
        (Self.debug ~level:3 "No interface file provided";
        None) 
      else  
        (
        let ispec = Parser_lib.Parse_ispec.parse_ispec_file ispec_file in
        Self.feedback "Parsed ispec successfully!";
        Some(ispec))
    in

    let log_file = NfrLogFile.get () in
    if Sys.file_exists log_file then Sys.remove log_file;

    (* Check which analyses to run *)
    (if CheckStatic.get () || CheckAll.get () then   
          (new verifyVarsAreStatic ispec)#run ());
    (if CheckOnlyEntries.get () || CheckAll.get () then 
          (new onlyEntryPointsDeclaredChecker ispec)#run ());
    (if CheckCalls.get () || CheckAll.get () then 
          (new whiteListFunCallsChecker ispec)#run ());
    (if CheckFunPtrs.get () || CheckAll.get () then 
          (new noFunctionPointerChecker ispec)#run ());
    (if CheckNoDefs.get () || CheckAll.get () then 
          (new noFunctionDefsChecker ispec)#run ());
    (if CheckProperInit.get () || CheckAll.get () then 
          (new properInitChecker ispec)#run ());
    (if CheckEntriesDeclared.get () || CheckAll.get () then 
          (new allEntryPointsDeclaredChecker ispec)#run ());
    (if CheckEntriesDefined.get () || CheckAll.get () then 
          (new allEntryPointsDefinedChecker ispec)#run ());
    (if CheckPtrLiterals.get () || CheckAll.get () then 
          (new ptrLiteralsChecker ispec)#run ());
    (if ChecNoPtrArith.get () || CheckAll.get () then 
          (new noPtrArithmeticsChecker ispec)#run ());
    (if CheckTypedefs.get () || CheckAll.get () then 
          (new typeDefChecker ispec)#run ())

    (* add to frama-c main pipeline *)
    let () = Boot.Main.extend run
