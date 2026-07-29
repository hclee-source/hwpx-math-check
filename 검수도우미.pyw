#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""검수도우미 — 더블클릭으로 여는 문항 검수 GUI.

hwpx(또는 items.json)를 골라 [검수 시작]을 누르면
파싱 → 정답↔해설 검산 → 쌍둥이 교차 → HTML 보고서를 브라우저로 띄운다.
"""
import os, sys, json, tempfile, threading, traceback, webbrowser
import tkinter as tk
from tkinter import filedialog, messagebox

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'scripts'))


class App:
    def __init__(self, root):
        self.root = root
        root.title('수학 문항 검수 도우미')
        root.geometry('640x420')
        root.resizable(True, True)

        self.paths = [tk.StringVar(), tk.StringVar()]
        frm = tk.Frame(root, padx=14, pady=10)
        frm.pack(fill='both', expand=True)

        tk.Label(frm, text='hwpx 문항 파일을 선택하세요. 2개면 쌍둥이 교차 검수까지 합니다.',
                 anchor='w').pack(fill='x')
        for i, cap in enumerate(['파일 1 (필수)', '파일 2 (선택)']):
            row = tk.Frame(frm)
            row.pack(fill='x', pady=3)
            tk.Label(row, text=cap, width=11, anchor='w').pack(side='left')
            tk.Entry(row, textvariable=self.paths[i]).pack(
                side='left', fill='x', expand=True, padx=4)
            tk.Button(row, text='찾아보기…',
                      command=lambda k=i: self.browse(k)).pack(side='left')

        self.btn = tk.Button(frm, text='검수 시작', height=2,
                             font=('Malgun Gothic', 11, 'bold'),
                             command=self.start)
        self.btn.pack(fill='x', pady=8)

        self.log = tk.Text(frm, height=12, state='disabled',
                           font=('Consolas', 9))
        self.log.pack(fill='both', expand=True)
        self.say('준비됨. 파일을 선택하고 [검수 시작]을 누르세요.')

    def browse(self, k):
        p = filedialog.askopenfilename(
            title='문항 파일 선택',
            filetypes=[('문항 파일', '*.hwpx *.json'), ('모든 파일', '*.*')])
        if p:
            self.paths[k].set(p)

    def say(self, msg):
        def _do():
            self.log.configure(state='normal')
            self.log.insert('end', msg + '\n')
            self.log.see('end')
            self.log.configure(state='disabled')
        self.root.after(0, _do)

    def start(self):
        files = [v.get().strip() for v in self.paths if v.get().strip()]
        if not files:
            messagebox.showwarning('알림', '파일 1을 선택하세요.')
            return
        for f in files:
            if not os.path.exists(f):
                messagebox.showerror('오류', f'파일이 없습니다:\n{f}')
                return
        self.btn.configure(state='disabled', text='검수 중…')
        threading.Thread(target=self.work, args=(files,), daemon=True).start()

    def work(self, files):
        try:
            import hwpx_items, math_review, report_html
            tmp = tempfile.mkdtemp(prefix='hwpx_check_')
            jsons = []
            for f in files:
                if f.lower().endswith('.json'):
                    jsons.append(f)
                    self.say(f'[입력] {os.path.basename(f)} (파싱 생략)')
                    continue
                self.say(f'[파싱] {os.path.basename(f)} …')
                recs, skipped = hwpx_items.parse(f)
                data = hwpx_items.to_items_json(recs, os.path.basename(f))
                out = os.path.join(tmp, os.path.splitext(
                    os.path.basename(f))[0] + '_items.json')
                json.dump(data, open(out, 'w', encoding='utf-8'),
                          ensure_ascii=False)
                self.say(f'       문항 {data["n"]}개 (표 건너뜀 {skipped}개)')
                if data['n'] == 0:
                    self.say('       ⚠ 문항이 없습니다 — 문항 은행 구조(2열 표)가 맞는지 확인')
                jsons.append(out)

            self.say('[검수] 정답↔해설 검산 + 조판 결함' +
                     (' + 쌍둥이 교차' if len(jsons) == 2 else '') + ' …')
            findings, stats, details, items = math_review.run(jsons)

            base = os.path.splitext(files[0])[0]
            html_path = base + '_검수보고서.html'
            open(html_path, 'w', encoding='utf-8').write(report_html.render(
                findings, stats, details, [os.path.basename(f) for f in files],
                items=items))
            json.dump({'findings': findings, 'stats': stats, 'details': details},
                      open(base + '_report.json', 'w', encoding='utf-8'),
                      ensure_ascii=False, indent=1)

            high = sum(1 for x in findings if x.get('sev') == 'high')
            self.say(f'완료: 결함 후보 {len(findings)}건 (높음 {high}건)')
            self.say(f'보고서: {html_path}')
            webbrowser.open('file:///' + html_path.replace('\\', '/'))
        except Exception:
            self.say('오류 발생:\n' + traceback.format_exc())
        finally:
            self.root.after(0, lambda: self.btn.configure(
                state='normal', text='검수 시작'))


if __name__ == '__main__':
    root = tk.Tk()
    App(root)
    root.mainloop()
