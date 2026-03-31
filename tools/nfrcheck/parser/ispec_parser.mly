%{
open Ispec
open Ispec_parse_error

let raise_parse_error msg =
  let pos = Parsing.symbol_start_pos () in
  raise (SpecError (ParseError (msg, pos)))


let decl_table : (string, ispec_decl) Hashtbl.t = Hashtbl.create 32
let lookup_decl name =
  match Hashtbl.find_opt decl_table name with
  | Some d -> d
  | None ->
    raise_parse_error (Printf.sprintf "Unknown function name: %s" name)
%}

(* -------------------------------------------------------------------------- *)
(* Tokens                                                                    *)
(* -------------------------------------------------------------------------- *)

%token MODULE
%token ENTRY_FUNCTIONS ENTRY_ORDER EXTERNAL_CALLS EXTERNAL_CALL_ORDER
%token LBRACE RBRACE COLON COMMA LT
%token VOID BOOL CHAR SHORT INT LONG FLOAT DOUBLE UNSIGNED SIGNED STRUCT CONST
%token <string> IDENT
%token LPAREN RPAREN STAR
%token EOF


(* -------------------------------------------------------------------------- *)
(* Start symbol and types                                                    *)
(* -------------------------------------------------------------------------- *)

%start spec
%type <ispec> spec
%type <ispec_param> param
%type <ispec_decl> decl
%%

(* -------------------------------------------------------------------------- *)
(* Top-level Spec Grammar                                                    *)
(* -------------------------------------------------------------------------- *)

spec:
    MODULE IDENT LBRACE
      ENTRY_FUNCTIONS COLON LBRACE decl_list RBRACE
      ENTRY_ORDER COLON LBRACE order_list RBRACE
      EXTERNAL_CALLS COLON LBRACE include_list RBRACE
      EXTERNAL_CALL_ORDER COLON LBRACE order_list RBRACE
    RBRACE EOF
    {
      {
        module_name = $2;
        entry_fns = $7;
        entry_order = List.map (fun (a,b) -> CalledBefore (a,b)) $12;
        extern_calls = {
          includes = $17;
          call_order = List.map (fun (a,b) -> CalledBefore (a,b)) $22
        };
      }
    }
  | error
    { raise_parse_error "invalid module or section structure" }

(* -------------------------------------------------------------------------- *)
(* Function declarations                                                     *)
(* -------------------------------------------------------------------------- *)

decl_list:
    /* empty */ { [] }
  | decl_list_nonempty { $1 }

decl_list_nonempty:
    decl { [$1] }
  | decl_list_nonempty COMMA decl { $1 @ [$3] }

decl:
    ispec_type fname LPAREN param_list RPAREN
      {
        let d = { ispec_ret_type = $1; ispec_fname = $2; ispec_params = $4 } in
        Hashtbl.replace decl_table $2 d;
        d
      }
  | error { raise_parse_error "invalid function declaration syntax" }

fname:
    IDENT { $1 }
  | error { raise_parse_error "expected function name" }

(* -------------------------------------------------------------------------- *)
(* Types (conflict-free version)                                             *)
(* -------------------------------------------------------------------------- *)

ispec_type:
    CONST pointer_type      { Const $2 }
  | pointer_type            { $1 }

pointer_type:
    base_type               { Base $1 }
  | pointer_type STAR       { Ptr $1 }
  | pointer_type STAR CONST       { Ptr (Const $1) }

base_type:
    VOID          { Void }
  | BOOL          { Bool }
  | CHAR          { Char }
  | SHORT         { Short }
  | INT           { Int }
  | LONG LONG     { LongLong }
  | LONG          { Long }
  | FLOAT         { Float }
  | DOUBLE        { Double }
  | UNSIGNED base_primitive { Unsigned (Some $2) }
  | UNSIGNED                { Unsigned None }
  | SIGNED base_primitive   { Signed (Some $2) }
  | SIGNED                  { Signed None }
  | STRUCT IDENT            { Struct $2 }
  | IDENT                   { Custom $1 }

base_primitive:
    CHAR { Char }
  | SHORT { Short }
  | INT { Int }
  | LONG { Long }

(* -------------------------------------------------------------------------- *)
(* Parameters                                                                *)
(* -------------------------------------------------------------------------- *)

param_list:
    /* empty */                    { [] }
  | param_list_nonempty             {
      match $1 with
      | [{ ispec_ptype = Base Void; ispec_pname = None }] -> []
      | ps -> ps
    }

param_list_nonempty:
    param                           { [$1] }
  | param_list_nonempty COMMA param { $1 @ [$3] }

param:
    ispec_type IDENT  { { ispec_ptype = $1; ispec_pname = Some $2 } }
  | ispec_type        { { ispec_ptype = $1; ispec_pname = None } }
  | error { raise_parse_error "invalid parameter declaration" }

(* -------------------------------------------------------------------------- *)
(* Includes and order constraints                                            *)
(* -------------------------------------------------------------------------- *)

include_item:
    IDENT COLON LBRACE decl_list RBRACE
      { { hfile = $1; fns = $4 } }
  | error { raise_parse_error "invalid include item" }

include_list:
    /* empty */ { [] }
  | include_item { [$1] }
  | include_list COMMA include_item { $1 @ [$3] }
order_pair:
    IDENT LT IDENT {
      let lhs = lookup_decl $1 in
      let rhs = lookup_decl $3 in
      (lhs, rhs)
    }
  | error { raise_parse_error "invalid order constraint" }

order_list:
    /* empty */ { [] }
  | order_pair { [$1] }
  | order_list COMMA order_pair { $1 @ [$3] }
