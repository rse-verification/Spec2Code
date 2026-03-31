(* errors.ml *)
type parse_error =
  | LexError of string * Lexing.position
  | ParseError of string * Lexing.position
  | OtherError of string

exception SpecError of parse_error

let string_of_position pos =
  Printf.sprintf "line %d, column %d"
    pos.Lexing.pos_lnum
    (pos.Lexing.pos_cnum - pos.Lexing.pos_bol + 1)

let string_of_error = function
  | LexError (msg, pos) ->
      Printf.sprintf "Lexical error at %s: %s" (string_of_position pos) msg
  | ParseError (msg, pos) ->
      Printf.sprintf "Syntax error at %s: %s" (string_of_position pos) msg
  | OtherError(msg) -> 
    Printf.sprintf "Other parsing error: %s" msg