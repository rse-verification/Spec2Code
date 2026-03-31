open Options
open Utils
open Parser_lib.Ispec

class virtual genericNFRChecker ispec = object (self)
  inherit Visitor.frama_c_inplace
  method virtual name : string
  method ispec: Parser_lib.Ispec.ispec option = ispec

  val unknown_loc = Cil_datatype.Location.unknown
  val mutable cil_file: Cil_types.file option = None
  val mutable entry_vis = None
  val mutable callable_vis = None


  method vi_from_ispec_decl isd =
    (* let typ = ispec_decl_to_cil_type isd in *)
    (* (TODO: CHECK TYPE COMPATIBILITY) *)
    let vi_opt = List.find_map (fun (x:Cil_types.global) -> match x with
          | GFunDecl(_, vi, _) | GFun({svar=vi; _}, _) when vi.vname = isd.ispec_fname -> Some(vi)
          | _ ->  None)
        (self#get_cil_file ()).globals
    in
    match vi_opt with
      | Some(vi) -> 
        Self.debug ~level:4 "varinfo found for %a" Printer.pp_varinfo vi;
        vi
      | None ->
        (
          let ftyp = ispec_decl_to_cil_type isd in
          let vi = Cil.makeGlobalVar isd.ispec_fname ftyp in
          Self.debug ~level:3 "not varinfo found for %a, making a new" Printer.pp_varinfo vi;
          vi
        )



  method make_entry_vis () = 
    entry_vis <- 
      Some(
        List.map 
          self#vi_from_ispec_decl  
          (self#get_ispec ()).entry_fns
      )
  
  
  method make_callable_vis () = 
    callable_vis <- 
      Some(
        List.concat_map 
          (fun restr_inc -> List.map 
            self#vi_from_ispec_decl 
            restr_inc.fns)
          (self#get_ispec ()).extern_calls.includes
      )

  
  method print_error ?(loc=unknown_loc) msg =
    if loc = unknown_loc then
      Self.warning "%s" msg 
    else  
      Self.warning "%s (at %a)" msg Printer.pp_location loc

  method get_ispec () = match ispec with
    | Some(ispec') -> ispec'
    | None -> Self.fatal "No ispec found, make sure that it is provided with the --nfr-ispec option"

  method get_cil_file (): Cil_types.file = match cil_file with
    | Some(cf) -> cf
    | None -> Self.fatal "No cil_file found"


  method get_entry_vis () = match entry_vis with
    | Some(ev) -> ev
    | None -> Self.fatal "No entry_vis found,  make sure that ispec is provided with the --nfr-ispec option"
  
  method private get_callable_vis () = match callable_vis with
    | Some(cv) -> cv
    | None -> Self.fatal "No callable_vis found,  make sure that ispec is provided with the --nfr-ispec option"
  
  method get_module_name () = 
      (self#get_ispec ()).module_name
  method file_is_this_module fname =
    let this_fname = self#get_module_name () in
    (this_fname ^ ".c" = fname) || (this_fname ^ ".h" = fname) 
    
  method get_hfile_deps () = 
    List.map (fun inc -> inc.hfile) (self#get_ispec ()).extern_calls.includes

  method run () = 
    Self.feedback "Running %s" self#name; 
    cil_file <- Some(Ast.get ());
    (if Option.is_some ispec then
      (self#make_entry_vis ();
      self#make_callable_vis ()));
    Visitor.visitFramacFileSameGlobals (self :> Visitor.frama_c_inplace) (self#get_cil_file ())

end