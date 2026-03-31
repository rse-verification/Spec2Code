open Printf
open Lexing
open Ispec
open Ispec_parse_error

(* -------------------------------------------------------------------------- *)
(* Utility: print position in the source file                                  *)
(* -------------------------------------------------------------------------- *)
let position_of_lexbuf lexbuf =
  let pos = lexbuf.lex_curr_p in
  sprintf "%s:%d:%d" pos.pos_fname pos.pos_lnum (pos.pos_cnum - pos.pos_bol + 1)

(* -------------------------------------------------------------------------- *)
(* Parse an .ispec file and return the AST                                     *)
(* -------------------------------------------------------------------------- *)
let parse_ispec_file filename : ispec =
  let ic = open_in filename in
  let lexbuf = Lexing.from_channel ic in
  lexbuf.lex_curr_p <- { lexbuf.lex_curr_p with pos_fname = filename };
  try
    let ast = Ispec_parser.spec Ispec_lexer.token lexbuf in
    close_in ic;
    ast
  with
  | SpecError (LexError (msg, pos)) ->
      eprintf "Lexical error at %s:%d:%d: %s\n"
        pos.pos_fname pos.pos_lnum (pos.pos_cnum - pos.pos_bol + 1) msg;
      close_in ic;
      exit 1
  | SpecError (ParseError (msg, pos)) ->
      eprintf "Parse error at %s:%d:%d: %s\n"
        pos.pos_fname pos.pos_lnum (pos.pos_cnum - pos.pos_bol + 1) msg;
      close_in ic;
      exit 1
  | End_of_file ->
      eprintf "Unexpected end of file while parsing %s\n" filename;
      close_in ic;
      exit 1