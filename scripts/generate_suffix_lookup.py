"""Generate suffix lookup table from training data"""
import csv, re, sys, os
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.by1_rule_engine import preprocess, extract_features

BASE_RE = re.compile(r'^([X]?D\d{2,3}[XFH])')

with open('zhhm_orders/edesc_by1_filtered.csv', 'r', encoding='utf-8') as f:
    rows = list(csv.DictReader(f))

lookup = {}
for r in rows:
    actual = r['by1']
    m = BASE_RE.match(actual)
    if not m:
        continue
    base_actual = m.group(1)
    suffix_actual = actual[len(base_actual):]

    clean = preprocess(r['EDesc'])
    feats = extract_features(clean)

    # Compute base code from features (same logic as engine)
    fire = feats['has_signal']
    conn = feats['connection']
    struct = feats['valve_structure']
    seat = feats['seat_material']
    has_lug = feats['has_lug']
    has_grooved = feats['has_grooved']
    has_gear = feats['actuation'] in ('GEAR',)
    has_flanged = feats.get('has_flanged', False)

    if fire:
        pos2 = "3"
    elif struct in ('2', '3') and has_flanged:
        pos2 = "3"
    elif conn in ('WAFER', 'LUG', 'LUG_WAFER', 'UNKNOWN') and not fire:
        pos2 = ""
    elif (conn == 'GROOVED' or has_grooved) and not fire:
        pos2 = ""
    elif conn == 'FLANGED' and struct == '1':
        pos2 = ""
    elif has_gear:
        pos2 = "3"
    else:
        pos2 = ""

    if conn == 'THREADED': pos3 = "1"
    elif conn == 'FLANGED': pos3 = "4"
    elif conn == 'GROOVED' or has_grooved: pos3 = "8"
    else: pos3 = "7"

    prefix = "X" if fire else ""
    base_pred = f"{prefix}D{pos2}{pos3}{struct}{seat}"

    key = (base_pred, feats['has_lug'], feats['is_higher_lever'],
           feats['is_lockable'], feats['disc_material'],
           feats.get('seat_name', ''), feats['actuation'])

    if key not in lookup:
        lookup[key] = Counter()
    lookup[key][suffix_actual] += 1

best = {k: v.most_common(1)[0][0] for k, v in lookup.items()}

# Base fallback
base_fb = {}
for k, suffix in best.items():
    base = k[0]
    if base not in base_fb:
        base_fb[base] = Counter()
    base_fb[base][suffix] += 1
base_fb = {k: v.most_common(1)[0][0] for k, v in base_fb.items()}

# Write output
lines = ['"""Auto-generated suffix lookup table - DO NOT EDIT"""', '']
lines.append('SUFFIX_LOOKUP = {')
for k in sorted(best.keys()):
    lines.append(f'    {k}: "{best[k]}",')
lines.append('}')
lines.append('')
lines.append('SUFFIX_LOOKUP_BASE = {')
for k in sorted(base_fb.keys()):
    lines.append(f'    "{k}": "{base_fb[k]}",')
lines.append('}')

out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'suffix_lookup_generated.py')
with open(out_path, 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))

print(f"Generated {len(best)} lookup entries, {len(base_fb)} base fallbacks")
print(f"Written to {out_path}")
