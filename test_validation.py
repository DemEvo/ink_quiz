from ink_validator import validate_ink
print(validate_ink(open('test_validation.ink','r',encoding='utf-8').read()))
print("\n")
print(validate_ink(open('valid.ink','r',encoding='utf-8').read()))
