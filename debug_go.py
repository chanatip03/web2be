import re

content = open(r'data/projects/6cf1dd6e263044a9b746e945af959fc3/routes/router.go', encoding='utf-8').read()
print('File content:')
print(content)
print()

pat_str = r'\.(GET|POST|PUT|DELETE|PATCH|OPTIONS|HEAD|HandleFunc|Handle|HandlerFunc)\s*\(\s*[\"\'\'\'\']((?:[^\"\'\'\'\']+))[\"\'\'\'\']]'

# Test simpler pattern
import re
pat1 = re.compile(r'\.(GET|POST|PUT|DELETE|PATCH)\s*\(\s*"([^"]+)"')
matches = list(pat1.finditer(content))
print(f'Pattern 1 (.GET("path", ...) - double quotes): {len(matches)} matches')
for m in matches:
    print(f'  {m.group(1)} {m.group(2)}')
