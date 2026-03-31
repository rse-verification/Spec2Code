{
  open Ispec_parser
  open Ispec_parse_error

  let raise_lex_error lexbuf msg =
    let pos = Lexing.lexeme_start_p lexbuf in
    raise (SpecError (LexError (msg, pos)))
}

(* --- regex definitions --- *)
let ws     = [' ' '\t' '\r' '\n']+
let ident  = ['A'-'Z' 'a'-'z' '_' '0'-'9' '.']+

rule token = parse
  | ws { token lexbuf }                            (* skip whitespace *)

  | "module"               { MODULE }
  | "entry_functions"      { ENTRY_FUNCTIONS }
  | "entry_order"          { ENTRY_ORDER }
  | "external_calls"       { EXTERNAL_CALLS }
  | "external_call_order"  { EXTERNAL_CALL_ORDER }

  | "{"                    { LBRACE }
  | "}"                    { RBRACE }
  | ":"                    { COLON }
  | ","                    { COMMA }
  | "<"                    { LT }
  | "("                    { LPAREN }
  | ")"                    { RPAREN }
  | "*"                    { STAR }

  (* C type keywords *)
  | "void"                 { VOID }
  | "bool"                 { BOOL }
  | "char"                 { CHAR }
  | "short"                { SHORT }
  | "int"                  { INT }
  | "long"                 { LONG }
  | "float"                { FLOAT }
  | "double"               { DOUBLE }
  | "unsigned"             { UNSIGNED }
  | "signed"               { SIGNED }
  | "struct"               { STRUCT }
  | "const"                { CONST }

  | ident as s             { IDENT s }

  | eof                    { EOF }

  | _ {
      let c = Lexing.lexeme_char lexbuf 0 in
      raise_lex_error lexbuf (Printf.sprintf "Unexpected char: %c" c)
  }
