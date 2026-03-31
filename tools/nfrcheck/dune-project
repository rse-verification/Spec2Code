(lang dune 3.13)
(using dune_site 0.1)
(using menhir 3.0)
(name frama-c-vernfr)

(generate_opam_files true)

(license GPL-2.0-or-later)
(maintainers "Jesper Amilon")
(authors "The VerNFR development team")
(source (github rse-verification/vernfr))
(homepage "https://github.com/rse-verification/vernfr")
(version dev)

(package
 (name frama-c-vernfr)
 (depends
  (ocaml (>= 4.14))
  (frama-c (and (>= 32) (< 33))))
 (synopsis "Frama-C plugin for verification on non-functional contracts")
 (description "This plugin for the Frama-C platform allows verification of
non-functional contracts, including properties on control flow and data flow.")
)
