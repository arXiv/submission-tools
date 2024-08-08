
regenerate_test_json:
	rm -f tests/*.json
	for i in tests/* ; do echo "=== $$i ===" ; python -m preflight_parser $$i | json_pp > $$i.json; done
