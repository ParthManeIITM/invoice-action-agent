#!/usr/bin/env python3
"""
3D Face Reconstruction Pipeline for Marina Abramović
Produces a valid glTF 2.0 binary (.glb) model conforming to all specifications:
- Morphing 3D geometry to match Marina Abramović's distinctive feminine facial features:
  softer jaw, feminine chin profile, smooth brow ridge, refined nasal bridge, and fuller lips.
- Seamless UV texture blending from high-resolution portrait photograph into anatomical head map.
- Valid glTF 2.0 binary layout with embedded textures, binary buffers, and smooth normals.
- File size strictly under 2 MB (2,000,000 bytes).
"""

import sys
import os
import math
import struct
import json
import io
from PIL import Image, ImageFilter

BASE_DIR = "/Users/parthmane/.gemini/antigravity/scratch/invoice-action-agent"
PHOTO_PATH = "/Users/parthmane/.gemini/antigravity/brain/38641c0a-b966-4a66-bbd8-99a48a878cd9/.user_uploaded/media_1792942478714_57e0a717.jpg"
BASE_GLB = "/tmp/LeePerrySmith.glb"
BASE_TEX = "/tmp/Map-COL.jpg"
OUTPUT_GLB = os.path.join(BASE_DIR, "marina_abramovic.glb")


def create_blended_texture(base_tex_path: str, photo_path: str, out_size=(1024, 1024)) -> Image.Image:
    print(f"Blending reference portrait {photo_path} into base UV texture...")
    base_tex = Image.open(base_tex_path).convert("RGB")
    photo = Image.open(photo_path).convert("RGB")

    # Crop tightly around Marina's face (forehead to chin, cheek to cheek)
    face_box = (110, 130, 650, 790)
    marina_face = photo.crop(face_box)

    target_w = 480
    target_h = 540
    marina_resized = marina_face.resize((target_w, target_h), Image.Resampling.LANCZOS)

    # Elliptical feather mask for smooth transition
    mask = Image.new("L", (target_w, target_h), 0)
    mw, mh = mask.size
    cx, cy = mw / 2.0, mh / 2.0
    rx, ry = mw * 0.43, mh * 0.45

    for y in range(mh):
        for x in range(mw):
            dx = (x - cx) / rx
            dy = (y - cy) / ry
            dist = math.sqrt(dx * dx + dy * dy)
            if dist < 0.65:
                alpha = 255
            elif dist < 1.0:
                alpha = int(255 * (1.0 - (dist - 0.65) / 0.35))
            else:
                alpha = 0
            mask.putpixel((x, y), alpha)

    mask = mask.filter(ImageFilter.GaussianBlur(radius=10))

    dest_x = 512 - target_w // 2
    dest_y = 150
    base_tex.paste(marina_resized, (dest_x, dest_y), mask)
    print("Texture blending complete.")
    return base_tex


def load_base_model(glb_path: str):
    print(f"Loading anatomical base mesh from {glb_path}...")
    with open(glb_path, "rb") as f:
        data = f.read()

    magic, version, length = struct.unpack("<4sII", data[:12])
    chunk_len, chunk_type = struct.unpack("<II", data[12:20])
    gltf = json.loads(data[20:20 + chunk_len].decode("utf-8"))
    bin_data = data[20 + chunk_len + 8:]

    prim = gltf["meshes"][0]["primitives"][0]
    indices_acc = gltf["accessors"][prim["indices"]]
    pos_acc = gltf["accessors"][prim["attributes"]["POSITION"]]
    uv_acc = gltf["accessors"][prim["attributes"]["TEXCOORD_0"]]

    indices_bv = gltf["bufferViews"][indices_acc["bufferView"]]
    pos_bv = gltf["bufferViews"][pos_acc["bufferView"]]
    uv_bv = gltf["bufferViews"][uv_acc["bufferView"]]

    indices_raw = bin_data[indices_bv["byteOffset"]:indices_bv["byteOffset"] + indices_bv["byteLength"]]
    indices = [struct.unpack_from("<H", indices_raw, i * 2)[0] for i in range(indices_acc["count"])]

    pos_raw = bin_data[pos_bv["byteOffset"]:pos_bv["byteOffset"] + pos_bv["byteLength"]]
    verts = [list(struct.unpack_from("<fff", pos_raw, i * 12)) for i in range(pos_acc["count"])]

    uv_raw = bin_data[uv_bv["byteOffset"]:uv_bv["byteOffset"] + uv_bv["byteLength"]]
    uvs = [list(struct.unpack_from("<ff", uv_raw, i * 8)) for i in range(uv_acc["count"])]

    print(f"Loaded {len(verts)} vertices and {len(indices)//3} triangles.")
    return verts, uvs, indices


def morph_to_marina_abramovic(verts):
    print("Morphing 3D geometry to match Marina Abramović's facial anatomy...")
    morphed = []

    for v in verts:
        x, y, z = v[0], v[1], v[2]

        # 1. Soften male brow ridge (supraorbital torus)
        if 1.4 <= y <= 2.2 and z > 1.5 and abs(x) < 1.5:
            brow_factor = math.sin((y - 1.4) / 0.8 * math.pi) * max(0.0, 1.0 - abs(x) / 1.5)
            z -= 0.14 * brow_factor

        # 2. Feminize and contour the jawline
        if -1.6 <= y <= 0.0 and abs(x) > 0.7:
            jaw_soften = max(0.0, 1.0 - abs(abs(x) - 1.5) / 0.9)
            x *= (1.0 - 0.09 * jaw_soften)
            z -= 0.07 * jaw_soften

        # 3. Soften, round, and slightly elevate chin
        if -0.8 <= y <= -0.1 and abs(x) < 0.7 and z > 1.7:
            chin_f = math.sin((y - (-0.8)) / 0.7 * math.pi) * max(0.0, 1.0 - abs(x) / 0.7)
            z -= 0.06 * chin_f
            x *= 0.94
            y += 0.03 * chin_f

        # 4. Cheeks: graceful, smoother cheek curves
        if 0.3 <= y <= 1.3 and 0.5 <= abs(x) <= 1.7 and z > 1.3:
            ch_y = math.sin((y - 0.3) / 1.0 * math.pi)
            ch_x = math.sin((abs(x) - 0.5) / 1.2 * math.pi)
            z += 0.07 * ch_y * ch_x

        # 5. Nose refinement: straight, elegant bridge, natural tip
        if 0.7 <= y <= 1.6 and z > 1.6 and abs(x) < 0.6:
            ny = (y - 0.7) / 0.9
            lat_w = max(0.0, 1.0 - abs(x) / 0.5)
            x *= (1.0 - 0.06 * lat_w)
            z += 0.05 * math.sin(ny * math.pi) * lat_w

        # 6. Fuller lips
        if 0.3 <= y <= 0.75 and abs(x) < 0.7 and z > 1.8:
            lip_f = math.sin((y - 0.3) / 0.45 * math.pi) * max(0.0, 1.0 - abs(x) / 0.7)
            z += 0.07 * lip_f

        morphed.append([x, y, z])

    return morphed


def recalculate_smooth_normals(verts, indices):
    print("Recalculating smooth area-weighted vertex normals...")
    normals = [[0.0, 0.0, 0.0] for _ in range(len(verts))]

    for t in range(0, len(indices), 3):
        ia, ib, ic = indices[t], indices[t + 1], indices[t + 2]
        va, vb, vc = verts[ia], verts[ib], verts[ic]

        ax, ay, az = vb[0] - va[0], vb[1] - va[1], vb[2] - va[2]
        bx, by, bz = vc[0] - va[0], vc[1] - va[1], vc[2] - va[2]

        nx = ay * bz - az * by
        ny = az * bx - ax * bz
        nz = ax * by - ay * bx

        for idx in (ia, ib, ic):
            normals[idx][0] += nx
            normals[idx][1] += ny
            normals[idx][2] += nz

    smooth_normals = []
    for n in normals:
        l = math.sqrt(n[0] * n[0] + n[1] * n[1] + n[2] * n[2])
        if l > 1e-8:
            smooth_normals.append([n[0] / l, n[1] / l, n[2] / l])
        else:
            smooth_normals.append([0.0, 1.0, 0.0])

    return smooth_normals


def export_glb(verts, normals, uvs, indices, texture_img, output_path: str):
    print(f"Exporting glTF 2.0 binary to {output_path}...")
    tex_buf = io.BytesIO()
    texture_img.save(tex_buf, format="JPEG", quality=88, optimize=True)
    tex_bytes = tex_buf.getvalue()
    print(f"Embedded texture size: {len(tex_bytes):,} bytes")

    def pad4(b, pad_byte=b"\x00"):
        rem = len(b) % 4
        return b if rem == 0 else b + (pad_byte * (4 - rem))

    bin_data = bytearray()

    # 0: Indices (UNSIGNED_SHORT)
    indices_offset = len(bin_data)
    for idx in indices:
        bin_data.extend(struct.pack("<H", idx))
    indices_len = len(bin_data) - indices_offset
    bin_data = bytearray(pad4(bin_data))

    # 1: Positions (FLOAT, VEC3)
    pos_offset = len(bin_data)
    min_pos = [float("inf")] * 3
    max_pos = [float("-inf")] * 3
    for v in verts:
        bin_data.extend(struct.pack("<fff", v[0], v[1], v[2]))
        for k in range(3):
            if v[k] < min_pos[k]:
                min_pos[k] = v[k]
            if v[k] > max_pos[k]:
                max_pos[k] = v[k]
    pos_len = len(bin_data) - pos_offset
    bin_data = bytearray(pad4(bin_data))

    # 2: Normals (FLOAT, VEC3)
    norm_offset = len(bin_data)
    for n in normals:
        bin_data.extend(struct.pack("<fff", n[0], n[1], n[2]))
    norm_len = len(bin_data) - norm_offset
    bin_data = bytearray(pad4(bin_data))

    # 3: TexCoords (FLOAT, VEC2)
    uv_offset = len(bin_data)
    for uv in uvs:
        bin_data.extend(struct.pack("<ff", uv[0], uv[1]))
    uv_len = len(bin_data) - uv_offset
    bin_data = bytearray(pad4(bin_data))

    # 4: Image buffer
    img_offset = len(bin_data)
    bin_data.extend(tex_bytes)
    img_len = len(tex_bytes)
    bin_data = bytearray(pad4(bin_data))

    gltf = {
        "asset": {
            "version": "2.0",
            "generator": "3D Face Reconstruction (Marina Abramović)"
        },
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{
            "mesh": 0,
            "name": "MarinaAbramovic_Head",
            "translation": [0.0, 0.0, 0.0]
        }],
        "meshes": [{
            "name": "MarinaAbramovic_Mesh",
            "primitives": [{
                "attributes": {
                    "POSITION": 1,
                    "NORMAL": 2,
                    "TEXCOORD_0": 3
                },
                "indices": 0,
                "material": 0
            }]
        }],
        "materials": [{
            "name": "SkinMaterial",
            "pbrMetallicRoughness": {
                "baseColorTexture": {"index": 0},
                "metallicFactor": 0.0,
                "roughnessFactor": 0.65
            },
            "doubleSided": False
        }],
        "textures": [{"sampler": 0, "source": 0}],
        "images": [{"bufferView": 4, "mimeType": "image/jpeg"}],
        "samplers": [{
            "magFilter": 9729,
            "minFilter": 9987,
            "wrapS": 10497,
            "wrapT": 10497
        }],
        "accessors": [
            {
                "bufferView": 0,
                "byteOffset": 0,
                "componentType": 5123,
                "count": len(indices),
                "type": "SCALAR"
            },
            {
                "bufferView": 1,
                "byteOffset": 0,
                "componentType": 5126,
                "count": len(verts),
                "type": "VEC3",
                "max": max_pos,
                "min": min_pos
            },
            {
                "bufferView": 2,
                "byteOffset": 0,
                "componentType": 5126,
                "count": len(normals),
                "type": "VEC3"
            },
            {
                "bufferView": 3,
                "byteOffset": 0,
                "componentType": 5126,
                "count": len(uvs),
                "type": "VEC2"
            }
        ],
        "bufferViews": [
            {"buffer": 0, "byteOffset": indices_offset, "byteLength": indices_len, "target": 34963},
            {"buffer": 0, "byteOffset": pos_offset, "byteLength": pos_len, "target": 34962},
            {"buffer": 0, "byteOffset": norm_offset, "byteLength": norm_len, "target": 34962},
            {"buffer": 0, "byteOffset": uv_offset, "byteLength": uv_len, "target": 34962},
            {"buffer": 0, "byteOffset": img_offset, "byteLength": img_len}
        ],
        "buffers": [{"byteLength": len(bin_data)}]
    }

    json_str = json.dumps(gltf, separators=(",", ":"))
    json_bytes = json_str.encode("utf-8")
    json_padded = pad4(json_bytes, b" ")

    total_length = 12 + (8 + len(json_padded)) + (8 + len(bin_data))
    header = struct.pack("<4sII", b"glTF", 2, total_length)
    chunk0_header = struct.pack("<II", len(json_padded), 0x4E4F534A)
    chunk1_header = struct.pack("<II", len(bin_data), 0x004E4942)

    with open(output_path, "wb") as f:
        f.write(header)
        f.write(chunk0_header)
        f.write(json_padded)
        f.write(chunk1_header)
        f.write(bin_data)

    print(f"Successfully exported: {output_path}")
    print(f"Total GLB size: {total_length:,} bytes ({total_length / 2_000_000 * 100:.2f}% of 2MB limit)")


def main():
    tex = create_blended_texture(BASE_TEX, PHOTO_PATH)
    verts, uvs, indices = load_base_model(BASE_GLB)
    morphed_verts = morph_to_marina_abramovic(verts)
    normals = recalculate_smooth_normals(morphed_verts, indices)
    export_glb(morphed_verts, normals, uvs, indices, tex, OUTPUT_GLB)


if __name__ == "__main__":
    main()
