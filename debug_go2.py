import re

content = open(r'data/projects/6cf1dd6e263044a9b746e945af959fc3/routes/router.go', encoding='utf-8').read()

patterns = [
    r'\.(GET|POST|PUT|DELETE|PATCH|OPTIONS|HEAD|HandleFunc|Handle|HandlerFunc)\s*\(\s*["\']([^"\']+)["\']',
]

for pat_str in patterns:
    pat = re.compile(pat_str, re.IGNORECASE)
    matches = list(pat.finditer(content))
    print(f'Pattern ({pat_str[:30]}...) - {len(matches)} matches')
    for m in matches:
        if m.re.groups == 2:
            print(f'  groups={m.lastindex} m_type={m.group(1)} path={m.group(2)}')
