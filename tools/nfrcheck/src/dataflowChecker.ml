open Options
open GenericNFRChecker
open Cil_types


class verifyVarsAreStatic ispec = object (self)
  inherit genericNFRChecker ispec

  method name = "StaticVariableChecker"

  method !vglob_aux (g: Cil_types.global) = 
    let () = match g with 
      | GVar(vi, _, loc) | GVarDecl(vi, loc) when vi.vghost = false ->
        (match vi.vstorage with 
          | Static -> Self.debug ~level:3 "Variable %a has static storage" Printer.pp_varinfo vi
          | _ -> self#print_error 
            ~loc:loc (Format.asprintf "Variable %a does not have static storage" Printer.pp_varinfo vi))
      | _ -> ()
    in
    Cil.SkipChildren
end
class ptrLiteralsChecker ispec = object (self)
  inherit genericNFRChecker ispec

  method name = "PointerLitealsChecker"

  method !vexpr (e: Cil_types.exp) = 
    (match e.enode with 
      | CastE(t, e') when Ast_types.is_ptr t -> 
        (match e'.enode with
          | Const(CInt64(_)) -> self#print_error ~loc:e.eloc 
              (Format.asprintf "Detected pointer literal %a" Printer.pp_exp e')
          | _ -> Self.debug ~level:3 "detected cast from non-integer constant to pointer type"
        )
      | _ -> ());
    Cil.SkipChildren
end

class properInitChecker ispec = object (self)
  inherit genericNFRChecker ispec

  method name = "properInitChecker"

  (* method get_all_inouts () =
    let actual_entry = (Globals.entry_point ()) in *)
    (* let make_inout_for_fn kf iomap = 
      begin
        Globals.set_entry_point (Kernel_function.get_name kf) false;
        Eva.Engine.Analysis.force_compute ();
        Kernel_function.Map.add kf (Inout.get_precise_inout kf) iomap
      end
    in
    let iomap = Globals.Functions.fold make_inout_for_fn Kernel_function.Map.empty in
    Globals.set_entry_point 
      (fst (Kernel_function.get_name actual_entry)) 
      (snd actual entry);
    iomap *)
    (* calls eva with each function as entry point. temporarily redirects stdout to logfile to 
     avoid flooding stdin with eva results *)
    method get_all_inouts () = 
    (*Redirect stdout*)
      let (entry_kf, lib_entry) = Globals.entry_point () in
      let all_inouts = 
        Globals.Functions.fold 
          (fun kf acc -> 
            Self.debug ~level:4 "Eva anlysis of %s" (Kernel_function.get_name kf);
            Globals.set_entry_point (Kernel_function.get_name kf) lib_entry;
            Utils.exec_with_redirected_stdout (NfrLogFile.get ()) Eva.Analysis.compute;
            
            Kernel_function.Map.add kf (Inout.get_precise_inout kf) acc
          )
          Kernel_function.Map.empty
      in
      Globals.set_entry_point (Kernel_function.get_name entry_kf) lib_entry;
      all_inouts
  method !vfile f = 
    let ispec = Option.get self#ispec in
    let no_init_vars = List.fold_left
      (fun acc g -> match g with 
        | GVar(vi, {init = None}, _) -> Locations.Zone.join (Locations.zone_of_varinfo vi) acc
        | _ -> acc  
      )
      Locations.Zone.bottom
      f.globals 
    in
    Self.feedback "getting inouts next";
    let all_inouts = self#get_all_inouts () in

    let check_fn isd =  
      let entry_vi = self#vi_from_ispec_decl isd in
      match Utils.vi_to_kf_opt entry_vi with
        | None -> Self.debug ~level:3 "no entry function find for %a" Printer.pp_varinfo entry_vi
        | Some(entry_kf) -> 
        let pred_vis = 
          List.map self#vi_from_ispec_decl (Utils.ISDSet.to_list (Utils.get_fns_called_before isd ispec))
        in
        List.iter (fun x -> Self.debug ~level:5 "predvis: %a" Printer.pp_varinfo x) pred_vis;  

        (*Get predecessors outputs*)
        (*TODO: Do we care if some kf is not defined? (should be sound anyway)*)
        let pred_kfs = List.filter_map Utils.vi_to_kf_opt pred_vis in
        let pred_outs = List.fold_left
          (fun acc kf -> Locations.Zone.join 
            (Kernel_function.Map.find kf all_inouts).over_outputs acc)
          Locations.Zone.bottom
          pred_kfs
        in
        (*Get current entry points inputs*)
        
        let entry_ins = (Kernel_function.Map.find entry_kf all_inouts).over_inputs in
        Self.debug ~level:4 "e_ins: %a" Locations.Zone.pretty entry_ins;
        (* we start with the global vars without explicit init, then we remove all 
          outputs for predecessor functions, and then take the intersection with the current entry
        *)
        let inputs_no_init = Locations.Zone.meet 
          entry_ins
          (Locations.Zone.diff no_init_vars pred_outs)
        in
        if Locations.Zone.is_bottom inputs_no_init then
          Self.feedback "All variables used have been initialised properly in %a"
            Printer.pp_varinfo entry_vi
        else 
          self#print_error (Format.asprintf "The following variables uses their \
            default value in %a: %a" 
            Printer.pp_varinfo (entry_vi)
            Locations.Zone.pretty inputs_no_init)

    in
    List.iter check_fn ispec.entry_fns;
    Cil.SkipChildren
        

    (* TODO:Continue here//;;; *)
end

class typeDefChecker ispec = object (self)
  inherit genericNFRChecker ispec

  method name = "TypeDefChecker"
  val mutable typedefs = []

  method print_typedef_error  ?(loc=unknown_loc) x t ti = 
    self#print_error 
      ~loc:loc 
      (Format.asprintf  "%s uses type %a instead of the defined typedef %s"
        x 
        Printer.pp_typ t
        ti.tname
      )
  
  method get_typedef t = 
    List.find_opt (fun ti -> Cil_datatype.TypByName.equal ti.ttype t) typedefs

  method !vfile f = 
    typedefs <- List.filter_map (fun g -> match g with | GType(ti, _) -> Some(ti) | _ -> None) f.globals;
    Cil.DoChildren
  
  method !vglob_aux g = (match g with 
    | GVar(vi, _, loc) | GVarDecl(vi, loc) -> 
      (match self#get_typedef vi.vtype with 
        | Some(ti) -> self#print_typedef_error ~loc:loc ("The variable " ^ vi.vname) vi.vtype ti 
        | None -> Self.debug ~level:5 "No typedefs for %a" Printer.pp_varinfo vi)
    | GFunDecl (_, vi, loc)  -> 
      (match self#get_typedef (Cil.getReturnType vi.vtype) with 
        | Some(ti) -> 
            self#print_typedef_error ~loc:loc ("The function " ^ vi.vname) vi.vtype ti 
        | None -> Self.debug ~level:5 "No typedefs for %a" Printer.pp_varinfo vi)
    | _ -> ()); 
    Cil.DoChildren
  
  method !vfunc fd = 
    (match self#get_typedef (Cil.getReturnType fd.svar.vtype) with 
      | Some(ti) -> self#print_typedef_error ("The function " ^ fd.svar.vname) fd.svar.vtype ti 
      | None -> Self.debug ~level:5 "No typedefs for %a" Printer.pp_varinfo fd.svar);
    List.iter 
      (fun vi -> match self#get_typedef vi.vtype with 
        | Some(ti) -> self#print_typedef_error ("In function " ^ fd.svar.vname ^ ", the variable " ^ vi.vname ) vi.vtype ti
        | None -> Self.debug ~level:5 "No typedefs for %a" Printer.pp_varinfo vi)
      (fd.slocals @ fd.sformals);
    Cil.DoChildren
      (* List.iter fd.svars *)
  
  method !vfieldinfo fi = 
    (match self#get_typedef fi.ftype with 
      | Some(ti) -> self#print_typedef_error ~loc:fi.floc ("In struct " ^ fi.fcomp.cname ^ ", the field " ^ fi.fname) fi.ftype ti 
      | None -> Self.debug ~level:5 "No typedefs for field %s in struct %s" fi.fname fi.fcomp.cname);
    Cil.DoChildren
  (* method !vexpr e = 
    match e.enode with 
      | CastE(t, _) -> 
        (match self#get_typedef t with 
          | Some(ti) -> self#print_typedef_error ~loc:e.eloc "Cast" t ti 
          | None -> Self.debug ~level:5 "Cast does not use typedef for type %a" Printer.pp_typ t);
          Cil.SkipChildren
      | _ -> Cil.SkipChildren *)


end