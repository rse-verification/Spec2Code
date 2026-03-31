#!/usr/bin/env bash

./data-flow-check.sh --folder ../case_studies/simple --modname simple --main simp_10ms
./control-flow-check.sh --folder ../case_studies/simple --modname simple --main simp_10ms

./data-flow-check.sh --folder ../case_studies/simple_f --modname simple --main simp_10ms
./control-flow-check.sh --folder ../case_studies/simple_f --modname simple --main simp_10ms