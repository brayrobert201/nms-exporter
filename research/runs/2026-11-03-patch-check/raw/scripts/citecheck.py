import glob, os, re
R = "/home/bob/Projects/nms-exporter/research/sources/game-data/"
W = "/tmp/nms-pak-scratch-20261103/files/"
for src in sorted(glob.glob(R + "*/**/*.xml", recursive=True)):
    rel = src[len(R):]; build, rest = rel.split("/", 1)
    m = re.match(r"(.*\.MXML)\.L(\d+)-(\d+)\.xml$", rest)
    if not m: continue
    cur = W + m.group(1)
    if not os.path.exists(cur): print("NOT UNPACKED", rel); continue
    body = [l.strip() for l in open(src).read().split("-->", 1)[-1].splitlines() if l.strip()]
    new = [l.strip() for l in open(cur).read().splitlines()]
    a, b = int(m.group(2)), int(m.group(3))
    seg = [l for l in new[a-1:b] if l]
    same_lines = body == seg
    txt = "\n".join(new); found = "\n".join(body) in txt
    print("%-8s same-at-lines=%s content-found-anywhere=%s  %s" % (build, same_lines, found, rel))
