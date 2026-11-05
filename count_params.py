with open('app/attendance/storage.py', 'r') as f:
    content = f.read()

# Find the params tuple
start = content.find('params = (')
if start != -1:
    depth = 0
    end = start
    for i, c in enumerate(content[start:]):
        if c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
            if depth == 0:
                end = start + i + 1
                break
    
    params_str = content[start:end]
    print('Params tuple length:', len(params_str))
    
    # Count items - split by newlines and look for record. lines
    lines = params_str.split('\n')
    count = 0
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('record.') or stripped.startswith('record.direction') or stripped.startswith('record.identity'):
            count += 1
    
    print('Total params (line count):', count)