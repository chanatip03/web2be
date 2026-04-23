content = open('/app/app/deployment/api/submission_preview.py').read()
old = 'result.get("services", [])'
new = 'result.get("service_ports", [])'
if old in content:
    content = content.replace(old, new)
    open('/app/app/deployment/api/submission_preview.py', 'w').write(content)
    print('Patched successfully')
else:
    print('Pattern not found, checking current content...')
    for i, line in enumerate(content.splitlines()):
        if 'service_ports' in line and 'result.get' in line:
            print(f'Line {i+1}: {line}')
