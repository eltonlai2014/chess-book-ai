"""Try all codecs on one stuck annotation."""
s = "磷\x00砆溃\r\n"
raw = s.encode("gb18030", errors="replace")
print("raw bytes:", raw.hex())
for codec in ["big5", "cp950", "big5hkscs", "gbk", "gb2312"]:
    try:
        out = raw.decode(codec, errors="replace")
        print(f"{codec}: {out!r}")
    except Exception as e:
        print(f"{codec}: ERROR {e}")
# Also try alternate src
print("--- via gbk encode ---")
try:
    raw2 = s.encode("gbk", errors="replace")
    print("raw2:", raw2.hex())
    for codec in ["big5", "cp950", "big5hkscs"]:
        print(f"{codec}: {raw2.decode(codec, errors='replace')!r}")
except Exception as e:
    print(e)
