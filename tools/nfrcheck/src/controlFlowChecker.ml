open Options
open Cil_types
open GenericNFRChecker
(* open Parser_lib.Ispec *)
open Utils


class onlyEntryPointsDeclaredChecker ispec = object (self)
  inherit genericNFRChecker ispec
  (*Does not warn if declared functions are in the whitelist of external calls*)

  method name = "onlyEntryPointsDeclaredChecker"
  method !vglob_aux g =
    (* let hfile_deps = self#get_hfile_deps () in *)
    let entry_vis = self#get_entry_vis () in
    let is_bad_decl vi loc =
      let () = Self.debug ~level:8  "in mod: %a" Format.pp_print_bool (self#file_is_this_module (loc_to_fname loc)) in
      not(viInList vi entry_vis) &&
      (self#file_is_this_module (loc_to_fname loc))
      (* not(List.mem (loc_to_fname loc) hfile_deps) *)
    in
    match g with
      | GFunDecl(_, vi, loc) when not(vi_is_static vi) ->
        (if is_bad_decl vi loc then
          self#print_error (Format.asprintf "The function %a is declared as non-static but not in the list \
            of entry functions" Printer.pp_varinfo vi) ~loc:loc
        else
          Self.debug ~level:3 "The function %a is declared and is in the list or is in another module"
            Printer.pp_varinfo vi);
        Cil.SkipChildren
      | GFun({svar = vi; _}, loc) when not (vi_is_static vi) ->
        (if not(viInList vi entry_vis) then
          self#print_error (Format.asprintf "The function %a is defined as non-static but not in the list \
            of entry functions" Printer.pp_varinfo vi) ~loc:loc
        else
          Self.debug ~level:3 "The function %a is defined and is in the list"
            Printer.pp_varinfo vi);
        Cil.SkipChildren
      | _ -> Cil.SkipChildren
end


class whiteListFunCallsChecker ispec = object (self)
  inherit genericNFRChecker ispec
  method name = "whiteListFunCallsChecker"

  method private check_vi ?(loc = unknown_loc) vi =
    Self.debug ~level:6 "%a" Format.pp_print_bool  (vi_is_static vi) ;

    if not(vi_is_static vi) && not(viInList vi (self#get_callable_vis ()))  then
      self#print_error ~loc:loc (Format.asprintf "Function call to %a, which is not in the whitelist"
        Printer.pp_varinfo vi)
    else
      Self.debug ~level:3 "Function call to %a (which is in the whitelist)"
        Printer.pp_varinfo vi

  method !vinst i =
    match i with
      | Call(_, lh, _, loc) ->
        (match lh with
          | Var(vi) -> self#check_vi ~loc:loc vi
          | Mem(_) ->
            Self.debug ~level:3 "mem lval in call exp: %a" Printer.pp_lhost lh);
        Cil.SkipChildren
      (* | Set()
        Cil.SkipChildren *)
      | Local_init(_, li, loc) -> (match li with
        | ConsInit(vi, _, _) -> self#check_vi ~loc:loc vi; Cil.SkipChildren
        | AssignInit(_) -> Cil.SkipChildren)
      | _ -> Cil.DoChildren

end



(* let isFunctionPtrType t = match Ast_types.unroll t with
  (| TPtr(t') -> match Ast_types.unroll t' with
        | TFun(_) -> true
        | -> false)
  | _ -> false  *)
(*  *)
class noFunctionPointerChecker ispec = object (self)
  inherit genericNFRChecker ispec

  method name = "NoFunctionPointersChecker"
  method !vexpr e = match e.enode with
    | Lval(Var(vi), _) ->
      (if Ast_types.is_fun_ptr vi.vtype then
        self#print_error
          ~loc:e.eloc (Format.asprintf "Found expression containing \
                        a function pointer %a" Printer.pp_varinfo vi));
        Cil.SkipChildren
    | AddrOf(Var(vi), _) ->
      (if Ast_types.is_fun vi.vtype then
        self#print_error
          ~loc:e.eloc (Format.asprintf "Found expression containing \
                        the address of a function: %a" Printer.pp_varinfo vi));
        Cil.SkipChildren
    | _ -> Cil.DoChildren
  (* method !vinst i = match i with
    | Call(_, e, pexps, loc) ->
        (match unroll_call_exp e with
          | Some(Mem(_)) ->
            self#print_error
              ~loc:loc (Format.asprintf "Found function call to a function pointer: %a" Printer.pp_exp e)
          | _ ->  ());
        Cil.SkipChildren
    | _ -> Cil.DoChildren *)
  (*NOTE: We dont have to check at local_inits, as calls to function pointers are moved from local inits
            during Frama-C normalization (or maybe preprocessing)
  **)

end

(** Checks that there are no function definitions in h-files. *)
class noFunctionDefsChecker ispec = object (self)
  inherit genericNFRChecker ispec
  (* Change so that this always checks, so user must run it only on h-files *)
  method name = "NoFunctionDefinitionsChecker"
  method !vglob_aux i = match i with
    | GFun (fd, loc) ->
        (self#print_error
          ~loc:loc (Format.asprintf "Found function definition: %a" Printer.pp_varinfo fd.svar));
        Cil.SkipChildren

      | _ -> Cil.SkipChildren
  (*NOTE: We dont have to check at local_inits, as calls to function pointers are moved from local inits
            during Frama-C normalization (or maybe preprocessing)
  **)

end

class noPtrArithmeticsChecker ispec = object (self)
  inherit genericNFRChecker ispec
  (* Change so that this always checks, so user must run it only on h-files *)
  method name = "PtrArithmeticsChecker"
  method !vexpr e = match e.enode with
    | BinOp(_, _, _, t) ->
        if Ast_types.is_ptr t then
          self#print_error
            ~loc:e.eloc (Format.asprintf "Found pointer arithmetic expression: %a" Printer.pp_exp e);
        Cil.DoChildren
    | _ -> Cil.DoChildren

end

class allEntryPointsDeclaredChecker ispec = object (self)
  inherit genericNFRChecker ispec

  method name = "AllEntryPointsDeclaredChecker"
  method !vfile f =
    let prog_decls = List.filter_map
      (fun g -> match g with
        | GFunDecl(_, vi, _) -> Some(vi)
        | _ -> None
      ) f.globals
    in
    let entry_decls = List.map self#vi_from_ispec_decl (self#get_ispec ()).entry_fns in
    let not_declared =
      VISet.diff (VISet.of_list entry_decls) (VISet.of_list prog_decls)
    in
    (if VISet.is_empty not_declared then Self.feedback "all specified entry points are declared"
    else
      VISet.iter
        (fun vi -> self#print_error ~loc:unknown_loc
          (Format.asprintf "The specified entry point %a is not declared"
          Printer.pp_varinfo vi))
        not_declared);
    Cil.SkipChildren
end

class allEntryPointsDefinedChecker ispec = object (self)
  inherit genericNFRChecker ispec

  method name = "AllEntryPointsDefinedChecker"
  method !vfile f =
    let prog_defs = List.filter_map
      (fun g -> match g with
        | GFun(fd, _) -> Some(fd)
        | _ -> None
      ) f.globals
    in
    let entry_decls = List.map self#vi_from_ispec_decl (self#get_ispec ()).entry_fns in
    let not_defined =
      VISet.diff
        (VISet.of_list entry_decls)
        (VISet.of_list (List.map (fun fd -> fd.svar) prog_defs))
    in
    (if VISet.is_empty not_defined then Self.feedback "all specified entry points are defined"
    else
      VISet.iter
        (fun vi -> self#print_error ~loc:unknown_loc
          (Format.asprintf "The specified entry point %a is not defined"
          Printer.pp_varinfo vi))
        not_defined);
    Cil.SkipChildren
end
