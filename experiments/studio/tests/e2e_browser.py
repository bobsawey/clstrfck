"""Browser check for the Studio prototype (Chromium via Playwright).

    pip install playwright && playwright install chromium
    python3 experiments/studio/tests/make_fixtures.py   # once
    python3 experiments/studio/tests/e2e_browser.py

Serves a temporary copy of the Studio (plus the previous committed index.html as
old.html, for the localStorage migration check) on 127.0.0.1 and drives it.
Uses only the fictional fixtures. Exits non-zero on the first failed check.
"""
import functools, http.server, json, os, shutil, socketserver, subprocess, sys, tempfile, threading
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

STUDIO = Path(__file__).resolve().parent.parent
FIXTURE = STUDIO / "tests" / "fixtures" / "jordan-career"
REPO = STUDIO.parent.parent

def serve(root):
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a): pass
    handler = functools.partial(Quiet, directory=str(root))
    srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/"

def check(cond, msg):
    if not cond:
        raise SystemExit("FAIL: " + msg)
    print("ok  -", msg)

def main():
    tmp = Path(tempfile.mkdtemp(prefix="studio-e2e-"))
    site = tmp / "site"; shutil.copytree(STUDIO, site, ignore=shutil.ignore_patterns("tests"))
    old = subprocess.run(["git", "show", "b84b10f:experiments/studio/index.html"], cwd=REPO, capture_output=True, text=True)
    if old.returncode == 0:
        (site / "old.html").write_text(old.stdout, encoding="utf-8")
    folder = tmp / "jordan-career"; shutil.copytree(FIXTURE, folder)
    (folder / "writing" / ".DS_Store").write_bytes(b"\x00hidden")  # ensure a hidden file is present
    srv, url = serve(site)
    errors = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(accept_downloads=True)
        page = ctx.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: m.type == "error" and errors.append(m.text))
        page.goto(url); page.wait_for_selector(".evidence-row")
        check(page.locator("#view-body .sample-strip").count() == 1, "sample banner shows on a fresh workspace")

        # --- blank workspace
        page.click("#view-body .sample-strip [data-action=blank-prompt]"); page.click("[data-action=start-blank]")
        page.wait_for_selector("text=Bring in what you already have")
        check(page.locator("#view-body .evidence-row").count() == 0, "blank workspace has no material")

        # --- folder import
        page.set_input_files("#folder-input", str(folder))
        page.wait_for_selector("#modal-title:has-text('Import finished')", timeout=30000)
        summary = page.locator(".import-summary").inner_text()
        print(summary.replace("\n", " | "))
        check("5\nImported" in summary, "five supported files imported (md, md, txt, pdf, docx)")
        check("Unsupported type" in summary and "photo.png" in page.locator(".import-summary").inner_html(), "unsupported file reported")
        check("Hidden, skipped" in summary, "hidden file reported as skipped")
        page.click("#modal [data-action=close-modal] >> nth=-1")
        body = page.locator("#view-body").inner_text()
        check("2022/resume.md" in body and "2024/resume.md" in body, "same-named files in nested folders stay distinct")
        check("PDF" in body and "DOCX" in body, "PDF and DOCX formats recorded")

        # --- search across formats
        def search(q):
            page.goto(url + "#library"); page.fill("#search", q); page.wait_for_timeout(300)
            return page.locator("#view-body").inner_text()
        check("feature-flag service" in search("feature-flag"), "PDF text is searchable")
        check("blameless postmortems" in search("postmortems"), "DOCX bullet is searchable")
        r = search("mentored four")
        check(page.locator("#view-body .evidence-row").count() == 1 and "2 sources" in r, "identical bullet in two résumés is one piece with two sources")
        check("Page two" in search("library"), "second PDF page extracted")

        # --- collect, editor, edit, export
        page.fill("#search", "feature-flag"); page.wait_for_timeout(300)
        page.click("#view-body .evidence-row .add-button")
        page.fill("#search", "Postgres"); page.wait_for_timeout(300)
        page.click("#view-body .evidence-row .add-button")
        page.goto(url + "#project/p1/editor"); page.wait_for_selector("text=Insert collected material")
        page.click("[data-action=insert-collected]")
        page.wait_for_selector(".block-text")
        first = page.locator(".block-text").first
        first.fill("Built a feature-flag service handling 2M evaluations/minute (edited).")
        page.wait_for_selector("#editor-save:has-text('Saved in this browser')")
        with page.expect_download() as dl:
            page.click("[data-action=export-editor]")
        md = Path(dl.value.path()).read_text(encoding="utf-8")
        check("(edited)" in md and "jordan-portfolio.pdf · page 1" in md and "Project-edited wording" in md, "Markdown export carries the edit, PDF page and source link")

        # --- persistence across reload
        page.reload(); page.wait_for_selector(".block-text")
        check("(edited)" in page.locator(".block-text").first.input_value(), "edited block survives reload (IndexedDB)")

        # --- reimport unchanged + changed snapshot
        (folder / "resumes" / "2024" / "resume.md").write_text("# Jordan Rivera — résumé 2024\n\n- Mentored five junior engineers.\n", encoding="utf-8")
        page.set_input_files("#folder-input", str(folder))
        page.wait_for_selector("#modal-title:has-text('Import finished')", timeout=30000)
        s2 = page.locator(".import-summary").inner_text()
        check("4\nUnchanged, skipped" in s2 and "1\nNew snapshot of a changed file" in s2, "re-import skips unchanged files and snapshots the changed one")
        page.click("#modal [data-action=close-modal] >> nth=-1")
        page.goto(url + "#project/p1/editor"); page.wait_for_selector(".block-text")
        check("(edited)" in page.locator(".block-text").first.input_value(), "project edit untouched by re-import")

        # --- drop: directory reader batches are drained (mocked entries, real code path)
        n = page.evaluate("""async()=>{
          const mkFile=(name)=>({isFile:true,isDirectory:false,name,file:(ok)=>ok(new File(['x'],name))});
          const kids=Array.from({length:250},(_,i)=>mkFile('f'+i+'.txt'));
          const dir={isFile:false,isDirectory:true,name:'big',createReader(){let i=0;return {readEntries(ok){const b=kids.slice(i,i+100);i+=100;setTimeout(()=>ok(b));}};}};
          const dt={items:[{kind:'file',webkitGetAsEntry:()=>dir}],files:[]};
          const r=await StudioExtract.filesFromDrop(dt);return [r.files.length,r.files[249].path];}""")
        check(n == [250, "big/f249.txt"], "drop walker reads every directory batch (250 entries in batches of 100)")
        # a real synthetic drop of a file (no directory entries available in synthetic events)
        page.evaluate("""()=>{const dt=new DataTransfer();dt.items.add(new File(['Dropped note about release trains.'],'dropped.md'));
          for(const t of ['dragenter','dragover','drop'])document.querySelector('#view-body').dispatchEvent(new DragEvent(t,{bubbles:true,cancelable:true,dataTransfer:dt}));}""")
        page.wait_for_selector("#modal-title:has-text('Import finished')", timeout=15000)
        check("1\nImported" in page.locator(".import-summary").inner_text(), "dropped file imported through the shared importer")
        page.click("#modal [data-action=close-modal] >> nth=-1")

        # --- internal drag/reorder still works (project material order)
        page.goto(url + "#project/p1/material"); page.wait_for_selector(".project-evidence .evidence-row")
        before = page.locator(".project-evidence .row-title").all_inner_texts()
        page.locator(".project-evidence .evidence-row").nth(1).drag_to(page.locator(".project-evidence .evidence-row").nth(0))
        page.wait_for_timeout(300)
        after = page.locator(".project-evidence .row-title").all_inner_texts()
        check(after == [before[1], before[0]], "in-app drag reorder still works")

        # --- export workspace, restore in a fresh browser context
        page.click("[data-action=settings]"); page.wait_for_selector("#storage-line:has-text('IndexedDB')")
        with page.expect_download() as dl:
            page.click("[data-action=export-workspace]")
        backup = Path(dl.value.path())
        data = json.loads(backup.read_text(encoding="utf-8"))
        check(data["format"] == "clstrfck-studio-workspace" and data["formatVersion"] == 1, "workspace export is versioned")

        ctx2 = browser.new_context(); p2 = ctx2.new_page()
        p2.on("pageerror", lambda e: errors.append("ctx2: " + str(e)))
        p2.goto(url); p2.wait_for_selector(".evidence-row")
        p2.click("[data-action=settings]"); p2.wait_for_selector("#storage-line")
        p2.set_input_files("#restore-input", str(backup))
        p2.wait_for_selector("#modal-title:has-text('Restore this workspace?')")
        p2.click("[data-action=confirm-restore]")
        p2.wait_for_timeout(500)
        p2.goto(url + "#project/p1/editor"); p2.wait_for_selector(".block-text")
        check("(edited)" in p2.locator(".block-text").first.input_value(), "restore in a fresh context reproduces project edits")
        p2.reload(); p2.wait_for_selector(".block-text")
        check("(edited)" in p2.locator(".block-text").first.input_value(), "restored workspace persisted")
        p2.click("[data-action=settings]"); p2.wait_for_selector("text=Before the last restore")
        check(True, "pre-restore recovery copy offered")
        # damaged file is rejected without changes
        bad = tmp / "bad.json"; d2 = json.loads(backup.read_text()); d2["workspace"]["facts"][0]["start"] += 3; bad.write_text(json.dumps(d2))
        p2.set_input_files("#restore-input", str(bad))
        p2.wait_for_selector("#modal-title:has-text('cannot be restored')")
        check(True, "damaged workspace file rejected before changing anything")
        ctx2.close()

        # --- two windows: remote update + stale write protection
        a = page; b = ctx.new_page(); b.on("pageerror", lambda e: errors.append("b: " + str(e)))
        b.goto(url + "#project/p1/editor"); b.wait_for_selector(".block-text")
        a.goto(url + "#project/p1/editor"); a.wait_for_selector(".block-text")
        a.locator(".block-text").first.fill("Changed in window A.")
        b.wait_for_function("document.querySelector('.block-text').value==='Changed in window A.'", timeout=5000)
        check(True, "second window picks up the change")
        # Simulate a write that window B never heard about (no broadcast), then edit in B.
        b.evaluate("""()=>new Promise((ok,no)=>{const r=indexedDB.open('clstrfck-studio');r.onsuccess=()=>{const tx=r.result.transaction('kv','readwrite'),st=tx.objectStore('kv'),g=st.get('workspace');g.onsuccess=()=>{const rec=g.result;rec.rev+=7;st.put(rec,'workspace');};tx.oncomplete=()=>ok();tx.onerror=()=>no(tx.error);};})""")
        b.locator(".block-text").first.fill("Stale edit in window B.")
        b.wait_for_selector("#modal-title:has-text('Another window saved first')", timeout=5000)
        check(b.locator(".block-text").first.input_value() == "Changed in window A.", "stale write refused; window shows saved version")
        b.click("#modal [data-action=close-modal]"); b.click("[data-action=settings]")
        b.wait_for_selector("text=Change refused because another window saved first")
        check(True, "refused change kept as a recovery copy")
        b.close()

        # --- legacy localStorage migration (previous committed version → this one, same origin)
        if (site / "old.html").exists():
            ctx3 = browser.new_context(); p3 = ctx3.new_page()
            p3.on("pageerror", lambda e: errors.append("ctx3: " + str(e)))
            p3.goto(url + "old.html#project/p1/editor"); p3.wait_for_selector("[data-action=insert-collected]")
            p3.click("[data-action=insert-collected]"); p3.wait_for_selector(".block-text")
            p3.locator(".block-text").first.fill("Legacy edit kept.")
            p3.wait_for_timeout(200)
            check(p3.evaluate("!!localStorage.getItem('clstrfck.studio.v1')"), "old version saved to localStorage")
            p3.goto(url + "#project/p1/editor"); p3.wait_for_selector(".block-text")
            check(p3.locator(".block-text").first.input_value() == "Legacy edit kept.", "old localStorage workspace migrates with project edits")
            p3.click("[data-action=settings]"); p3.wait_for_selector("text=Pre-IndexedDB copy")
            check(True, "legacy copy retained as a recovery copy")
            ctx3.close()

        # --- no runtime errors
        noisy = [e for e in errors if "favicon" not in e]
        check(not noisy, "no page errors: " + "; ".join(noisy[:5]))
        browser.close()
    srv.shutdown(); shutil.rmtree(tmp, ignore_errors=True)
    print("all browser checks passed")

if __name__ == "__main__":
    main()
