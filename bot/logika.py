"""Penyusun teks balasan bot — dipisah supaya bisa diuji tanpa Telegram."""

from __future__ import annotations

import html


def esc(teks) -> str:
    return html.escape(str(teks if teks is not None else "-"))


def rp(nilai) -> str:
    try:
        return "Rp " + f"{float(nilai or 0):,.0f}".replace(",", ".")
    except (TypeError, ValueError):
        return "Rp 0"


def _tanggal(nilai) -> str:
    teks = str(nilai or "")
    if len(teks) >= 10 and teks[4] == "-":
        bulan = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]
        try:
            return f"{int(teks[8:10])} {bulan[int(teks[5:7]) - 1]}"
        except (ValueError, IndexError):
            return teks[:10]
    return teks or "-"


def pesan_bantuan(username: str) -> str:
    return (
        "🧺 <b>Bot Lemari</b>\n"
        "Ade bantu jaga catatan barang yang dipakai ya kak.\n\n"
        "Kirim <b>foto barang</b> ke topik ini → ade baca isinya, lalu kakak tinggal tekan Simpan.\n\n"
        "<b>Perintah</b> (pakai @" + esc(username) + " kalau perlu):\n"
        "/ringkas — kondisi lemari hari ini\n"
        "/kotor — barang yang siap dicuci\n"
        "/cuci — batch cuci &amp; laundry yang jalan\n"
        "/pinjam — pinjaman yang belum kembali\n"
        "/cari &lt;kata&gt; — cari barang\n"
        "/stat — angka statistik ringkas\n"
        "/bantu — pesan ini\n\n"
        "Ade cuma balas di topik ini dan cuma buat kakak. Diam kalau tidak ada yang perlu."
    )


def pesan_ringkas(data: dict) -> str:
    if not data.get("ok"):
        return f"Maaf kak, datanya belum bisa ade ambil: {esc(data.get('pesan', 'tidak diketahui'))}"
    r = data["ringkas"]
    baris = [
        "🧺 <b>Kondisi lemari</b>",
        f"- Barang tercatat: <b>{r['barang']}</b> (nilai {rp(r['nilai'])})",
        f"- Siap dicuci: <b>{r['kotor']}</b>",
        f"- Sedang dicuci / di laundry: {r['sedang_dicuci']} (batch jalan: {r['batch_jalan']})",
    ]
    if r["laundry_lewat"]:
        baris.append(f"- ⚠️ Laundry lewat estimasi: <b>{r['laundry_lewat']}</b>")
    baris.append(f"- Pinjaman belum kembali: {r['pinjam_aktif']}" + (f" (lewat tempo: {r['pinjam_lewat']})" if r["pinjam_lewat"] else ""))
    baris.append(f"- Dipakai hari ini: {r['pakai_hari_ini']} · 30 hari: {r['pakai_30']}")
    baris.append(f"- Laundry bulan ini: {rp(r['laundry_bulan_ini'])}")
    if r["tanpa_harga"]:
        baris.append(f"- {r['tanpa_harga']} barang belum ada harga (cost per wear-nya kosong)")
    if r["wishlist"]:
        baris.append(f"- Wishlist: {rp(r['wishlist'])}")
    return "\n".join(baris)


def pesan_statistik(data: dict) -> str:
    if not data.get("ok"):
        return f"Maaf kak, datanya belum bisa ade ambil: {esc(data.get('pesan', 'tidak diketahui'))}"
    r = data["ringkas"]
    return (
        "📊 <b>Angka ringkas</b>\n"
        f"- Nilai lemari: <b>{rp(r['nilai'])}</b> dari {r['barang']} barang\n"
        f"- Rata-rata per barang: {rp(r['nilai'] / r['barang']) if r['barang'] else '-'}\n"
        f"- Dasar hitung cost per wear: {r['barang'] - r['tanpa_harga']} barang punya harga\n"
        f"- Pemakaian tercatat: {r['pakai_30']} kali dalam 30 hari\n"
        f"- Laundry bulan ini: {rp(r['laundry_bulan_ini'])}\n\n"
        "Rincian lengkap (cost per wear, nganggur, tren belanja) ada di menu Statistik web ya kak."
    )


def pesan_kotor(data: dict, domain: str = "lemari.dipo.sh") -> str:
    if not data.get("ok"):
        return f"Maaf kak, datanya belum bisa ade ambil: {esc(data.get('pesan', 'tidak diketahui'))}"
    barang = data.get("barang", [])
    if not barang:
        return "✨ Tidak ada barang berstatus kotor. Semua bersih kak."
    baris = [f"🧺 <b>{data['total']} barang siap dicuci</b>"]
    for b in barang[:20]:
        baris.append(f"- {esc(b['nama'])} · {esc(b['kategori'])} · {esc(b['lokasi'])}")
    if data["total"] > 20:
        baris.append(f"- … dan {data['total'] - 20} barang lain")
    baris.append(f"\nBuka menu Cuci di web buat bikin batch: https://{domain}/cuci")
    return "\n".join(baris)


def pesan_cuci(data: dict, domain: str = "lemari.dipo.sh") -> str:
    if not data.get("ok"):
        return f"Maaf kak, datanya belum bisa ade ambil: {esc(data.get('pesan', 'tidak diketahui'))}"
    batch = data.get("batch", [])
    nyangkut = data.get("nyangkut", [])
    if not batch and not nyangkut:
        return "✨ Tidak ada cucian yang jalan, tidak ada yang nyangkut. Bersih kak."

    baris = []
    if batch:
        baris.append(f"🧺 <b>{len(batch)} batch berjalan</b>")
        for b in batch:
            judul = "Cuci sendiri" if b["jalur"] == "sendiri" else f"Laundry {esc(b.get('nama_laundry') or '(tanpa nama)')}"
            kepala = f"- <b>{judul}</b> · {b['jumlah']} barang · jalan {b['hari']} hari"
            baris.append(kepala)
            baris.append(f"  isi: {esc(b['barang'])}")
            if b["jalur"] == "laundry":
                if b.get("estimasi_selesai"):
                    tanda = " ⚠️ lewat estimasi" if b.get("lewat_estimasi") else ""
                    baris.append(f"  estimasi: {_tanggal(b['estimasi_selesai'])}{tanda}")
                if b["biaya"]:
                    baris.append(f"  biaya: {rp(b['biaya'])}")
            if b["hari"] > 7:
                baris.append("  ⚠️ sudah lebih dari sepekan, cek ya kak")
    if nyangkut:
        baris.append(f"\n⚠️ <b>{len(nyangkut)} barang nyangkut</b> (status dicuci/laundry tapi tidak ada batch jalan)")
        for n in nyangkut[:10]:
            baris.append(f"- {esc(n['nama'])} ({esc(n['status'])})")
    baris.append(f"\nKelola di: https://{domain}/cuci")
    return "\n".join(baris)


def pesan_pinjam(data: dict, domain: str = "lemari.dipo.sh") -> str:
    if not data.get("ok"):
        return f"Maaf kak, datanya belum bisa ade ambil: {esc(data.get('pesan', 'tidak diketahui'))}"
    daftar = data.get("pinjaman", [])
    if not daftar:
        return "✨ Tidak ada pinjaman yang belum kembali."
    keluar = [p for p in daftar if p["arah"] == "keluar"]
    masuk = [p for p in daftar if p["arah"] == "masuk"]
    baris = ["🤝 <b>Pinjaman belum kembali</b>"]
    if keluar:
        baris.append("\n<b>Dipinjamkan ke orang lain</b>")
        for p in keluar:
            tempo = f" · jatuh tempo {_tanggal(p['jatuh_tempo'])}" if p.get("jatuh_tempo") else ""
            tanda = f" ⚠️ lewat {p['lewat_hari']} hari" if p.get("lewat_hari") else ""
            baris.append(f"- {esc(p['barang'])} → {esc(p['nama_pihak'])}{tempo}{tanda}")
    if masuk:
        baris.append("\n<b>Kakak pinjam dari orang lain</b>")
        for p in masuk:
            tempo = f" · harus kembali {_tanggal(p['jatuh_tempo'])}" if p.get("jatuh_tempo") else ""
            tanda = f" ⚠️ lewat {p['lewat_hari']} hari" if p.get("lewat_hari") else ""
            baris.append(f"- {esc(p['barang'])} ← {esc(p['nama_pihak'])}{tempo}{tanda}")
    baris.append(f"\nCatat pengembaliannya di: https://{domain}/pinjam")
    return "\n".join(baris)


def pesan_cari(data: dict) -> str:
    if not data.get("ok"):
        return f"Maaf kak, datanya belum bisa ade ambil: {esc(data.get('pesan', 'tidak diketahui'))}"
    barang = data.get("barang", [])
    if not barang:
        return f"Tidak ketemu barang dengan kata “{esc(data.get('kata'))}”."
    baris = [f"🔎 <b>{len(barang)} barang cocok dengan “{esc(data.get('kata'))}”</b>"]
    for b in barang:
        dipakai = f" · dipakai {b['dipakai']}×" if b.get("dipakai") else " · belum pernah dipakai"
        baris.append(f"- {esc(b['nama'])} · {esc(b['status'])} · {esc(b['kategori'])}{dipakai}")
    return "\n".join(baris)


def pesan_usulan(saran: dict) -> str:
    yakin = saran.get("yakin", True)
    kepala = "🧺 <b>Ini yang ade lihat</b>" if yakin else "🧺 <b>Ini yang ade lihat</b> (ade agak ragu, cek dulu ya kak)"
    baris = [kepala, f"- Nama: <b>{esc(saran.get('nama'))}</b>"]
    if saran.get("kategori"):
        baris.append(f"- Kategori: {esc(saran['kategori'])}")
    for kunci, label in (("jenis", "Jenis"), ("warna_utama", "Warna"), ("warna_sekunder", "Warna kedua"),
                         ("bahan", "Bahan"), ("pola", "Pola"), ("okasi", "Okasi"), ("catatan", "Catatan")):
        if saran.get(kunci):
            baris.append(f"- {label}: {esc(saran[kunci])}")
    baris.append("\nMau ade simpan ke katalog? Bisa juga dilengkapi dulu (harga, tanggal beli) lewat web.")
    return "\n".join(baris)


def pesan_tersimpan(nama: str, item_id, domain: str) -> str:
    return (
        f"✅ Tersimpan: <b>{esc(nama)}</b>\n"
        f"Halaman barangnya: https://{esc(domain)}/item/{esc(item_id)}\n"
        "Harga dan tanggal beli bisa ditambah di situ supaya cost per wear-nya kehitung."
    )
