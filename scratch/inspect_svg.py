# Calculate aspect ratios and bounding boxes
print("Comparing icon bounds:")
icons = {
    "google": {"viewBox": "0 0 24 24", "width_range": (3.21, 21.35), "height_range": (2, 22)},
    "instagram": {"viewBox": "0 0 24 24", "width_range": (0.05, 23.95), "height_range": (0.05, 23.95)},
    "twitter": {"viewBox": "0 0 24 24", "width_range": (1.25, 21.55), "height_range": (2.25, 21.75)},
    "facebook": {"viewBox": "0 0 24 24", "width_range": (0, 24), "height_range": (0, 23.93)},
    "linkedin_orig": {"viewBox": "0 0 24 24", "width_range": (3, 21), "height_range": (3, 21)},
    "linkedin_new": {"viewBox": "2.5 2.5 19 19", "width_range": (3, 21), "height_range": (3, 21)},
}

for name, d in icons.items():
    w = d["width_range"][1] - d["width_range"][0]
    h = d["height_range"][1] - d["height_range"][0]
    vb_w = float(d["viewBox"].split()[2])
    vb_h = float(d["viewBox"].split()[3])
    # Fraction of viewBox occupied
    print(f"{name:15}: size {w:.2f}x{h:.2f} in vb {vb_w:.1f}x{vb_h:.1f} -> {w/vb_w*100:.1f}% width, {h/vb_h*100:.1f}% height")

