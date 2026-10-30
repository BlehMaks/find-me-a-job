"""Find Me a Job desktop setup. Packaged builds include Python and Tk."""
import argparse
import json
from pathlib import Path
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import webbrowser

if not getattr(sys, 'frozen', False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fmj.installer import Cancelled, Handoff, Options, Runner, agent_status, github_login, probe, setup


class Wizard:
    def __init__(self, root):
        self.root = root
        self.events = queue.Queue()
        self.runner = None
        self.busy = False
        self.url = None
        self.result = None
        root.title('Find Me a Job — Setup')
        root.geometry('920x760')
        root.minsize(760, 660)
        root.configure(background='#fbfbf9')
        style = ttk.Style(root)
        style.configure('TFrame', background='#fbfbf9')
        style.configure('TLabel', background='#fbfbf9', foreground='#161616', font=('Helvetica', 12))
        style.configure('TCheckbutton', background='#fbfbf9', font=('Helvetica', 11))
        style.configure('Title.TLabel', font=('Helvetica', 27, 'bold'))
        style.configure('Status.TLabel', foreground='#1747ee')
        outer = ttk.Frame(root, padding=28)
        outer.pack(fill='both', expand=True)
        ttk.Label(outer, text='fmj /  Set up your workspace', style='Title.TLabel').pack(anchor='w')
        ttk.Label(outer, text='Local source. A separate private folder. Your own agent account.').pack(anchor='w', pady=(6, 18))
        form = ttk.Frame(outer)
        form.pack(fill='x')
        form.columnconfigure(1, weight=1)
        self.agent = tk.StringVar(value='codex')
        self.interface = tk.StringVar(value='desktop')
        self.feedback = tk.StringVar(value='Ask later')
        self.source = tk.StringVar(value=str(Path.home() / 'FindMeAJob/source'))
        self.workspace = tk.StringVar(value=str(Path.home() / 'FindMeAJob/private'))
        self.desktop = tk.StringVar()
        self.dependencies = tk.BooleanVar(value=sys.platform == 'darwin')
        self.controls = []
        for row, (label, variable, choices) in enumerate((('Agent', self.agent, ('codex', 'claude')),
                                                       ('Interface', self.interface, ('desktop', 'cli')),
                                                       ('Generic improvements', self.feedback, ('Ask later', 'Allow generic improvements', 'Keep improvements local')))):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky='w', padx=(0, 18), pady=5)
            field = ttk.Combobox(form, textvariable=variable, values=choices, state='readonly', width=30 if row == 2 else 20)
            field.grid(row=row, column=1, sticky='w')
            self.controls.append(field)
        for row, (label, variable) in enumerate((('Source checkout', self.source), ('Private workspace', self.workspace),
                                                ('Custom desktop app (optional)', self.desktop)), start=3):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky='w', pady=5)
            entry = ttk.Entry(form, textvariable=variable)
            entry.grid(row=row, column=1, sticky='ew', pady=5)
            button = ttk.Button(form, text='Choose…', command=lambda v=variable: self.choose(v))
            button.grid(row=row, column=2, padx=(8, 0))
            self.controls.extend((entry, button))
        self.desktop_status = tk.StringVar()
        self.cli_status = tk.StringVar()
        for status in (self.desktop_status, self.cli_status):
            ttk.Label(outer, textvariable=status, wraplength=840).pack(anchor='w', pady=(4, 0))
        for variable in (self.agent, self.interface, self.desktop):
            variable.trace_add('write', self.reset_agent_status)
        self.reset_agent_status()
        check = ttk.Checkbutton(outer, text='Allow installation of missing software from the displayed package sources', variable=self.dependencies)
        check.pack(anchor='w', pady=(12, 3))
        self.controls.append(check)
        ttk.Label(outer, text='Allow generic improvements = reviewed issues/PRs from your account.\n'
                             'No personal records are sent. GitHub Desktop is optional. Paid agent access is recommended.').pack(anchor='w')
        self.status = tk.StringVar(value='Review the plan before installing. Nothing has been changed.')
        ttk.Label(outer, textvariable=self.status, style='Status.TLabel', wraplength=840).pack(anchor='w', pady=(15, 8))
        self.progress = ttk.Progressbar(outer, mode='indeterminate')
        self.progress.pack(fill='x', pady=(0, 8))
        self.output = tk.Text(outer, height=11, wrap='word', font=('Courier', 11), background='#f0f2fb',
                              foreground='#161616', relief='flat', padx=12, pady=10, state='disabled')
        footer = ttk.Frame(outer)
        footer.pack(side='bottom', fill='x', pady=(12, 0))
        buttons = ttk.Frame(footer)
        buttons.pack(fill='x')
        self.plan_button = ttk.Button(buttons, text='Check & review plan', command=lambda: self.start('check'))
        self.plan_button.pack(side='left')
        self.install_button = ttk.Button(buttons, text='Install / retry', command=self.confirm)
        self.install_button.pack(side='left', padx=7)
        self.login_button = ttk.Button(buttons, text='Sign in to GitHub', command=self.login)
        self.login_button.pack(side='left')
        self.stop_button = ttk.Button(buttons, text='Stop', command=self.stop, state='disabled')
        self.stop_button.pack(side='right')
        self.link_button = ttk.Button(footer, text='Open required step', command=self.open_step, state='disabled')
        self.link_button.pack(anchor='e', pady=(8, 0))
        self.copy_button = ttk.Button(footer, text='Copy first message', command=self.copy_starter, state='disabled')
        self.copy_button.pack(anchor='e', pady=(4, 0))
        self.output.pack(fill='both', expand=True)
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.after(100, self.poll)

    def choose(self, variable):
        if variable is self.desktop:
            value = filedialog.askopenfilename(parent=self.root, title='Choose the installed desktop application')
        else:
            value = filedialog.askdirectory(parent=self.root, title='Choose a folder (you can edit the final path)')
        if value:
            variable.set(value)

    def reset_agent_status(self, *_):
        desktop_mode = self.interface.get() == 'desktop'
        self.desktop_status.set(f'Desktop app ({"required" if desktop_mode else "optional"}): not checked')
        self.cli_status.set(f'CLI ({"optional for desktop" if desktop_mode else "required"}): not checked')

    def options(self):
        return Options(Path(self.source.get()), Path(self.workspace.get()), self.agent.get(),
                       self.interface.get(), {'Ask later': 'unset', 'Allow generic improvements': 'enabled', 'Keep improvements local': 'disabled'}[self.feedback.get()], self.dependencies.get(), self.desktop.get())

    def write(self, message):
        self.output.configure(state='normal')
        self.output.insert('end', str(message).rstrip() + '\n')
        lines = int(self.output.index('end-1c').split('.')[0])
        if lines > 250:
            self.output.delete('1.0', str(lines - 250) + '.0')
        self.output.see('end')
        self.output.configure(state='disabled')

    def confirm(self):
        try:
            self.options().validate()
        except Handoff as error:
            messagebox.showerror('Choose safe locations', str(error), parent=self.root)
            return
        if messagebox.askokcancel('Review setup', self.plan_text(), parent=self.root):
            self.start('install')

    def plan_text(self):
        return ('Source: ' + self.source.get() + '\nPrivate workspace: ' + self.workspace.get() +
                '\nAgent: ' + self.agent.get() + ' / ' + self.interface.get() + '\nFeedback: ' + self.feedback.get() +
                '\n\nThe source will be cloned or reused without reset. Existing workspace data is preserved. '
                'With missing-software installation allowed, macOS setup downloads and installs Homebrew and BasicTeX when needed; '
                'other tools use Homebrew or WinGet (Windows), including community Poppler builds on Windows. '
                'On macOS, you may need to allow software and packages downloaded from the internet in System Settings > Privacy & Security '
                'if permission has not already been granted. '
                'Some system installations need your native confirmation. No subscription is purchased; no account is signed in automatically. '
                'With enabled feedback, missing local Git identity uses your GitHub login and noreply address; global settings are preserved. '
                'Sign-in and feedback are separate choices. Stop prevents later steps; it does not undo native installations.')

    def login(self):
        if messagebox.askokcancel('GitHub authorization', 'Open GitHub browser authorization for this computer? '
                                 'This enables authenticated access through GitHub CLI. It does not enable feedback or send any issue/PR.', parent=self.root):
            self.start('login')

    def start(self, action):
        if self.busy:
            return
        try:
            options = self.options()
            options.validate()
        except Handoff as error:
            self.write(error)
            return
        plan = self.plan_text()
        self.busy = True
        self.url = None
        self.result = None
        self.link_button.configure(state='disabled')
        self.copy_button.configure(state='disabled')
        for widget in self.controls + [self.plan_button, self.install_button, self.login_button]:
            widget.configure(state='disabled')
        self.stop_button.configure(state='normal')
        self.progress.start(12)
        self.status.set('Checking…' if action == 'check' else 'Working — native confirmation may be required.')
        self.runner = Runner(lambda message: self.events.put(('output', message)))
        def work():
            try:
                if action == 'check':
                    result = probe(self.runner)
                    self.events.put(('output', plan))
                    statuses = agent_status(options, result)
                    self.events.put(('agent-status', statuses))
                    self.events.put(('output', '\n' + '\n'.join(statuses)))
                    dependencies = {key: value for key, value in result.items() if key not in {'codex', 'claude', 'desktop_apps'}}
                    self.events.put(('output', '\nOther setup tools (presence only): ' + json.dumps(dependencies, indent=2)))
                    self.events.put(('done', 'Plan checked. Account, quota and browser/mail permissions remain unverified.'))
                elif action == 'login':
                    verified = github_login(self.runner)
                    self.events.put(('done', 'GitHub CLI is authenticated. Feedback consent is unchanged.' if verified else 'GitHub sign-in is still incomplete.'))
                else:
                    result = setup(options, self.runner)
                    self.events.put(('result', result))
            except (Handoff, Cancelled) as error:
                self.events.put(('blocked', (str(error), getattr(error, 'url', None))))
            except Exception:
                self.events.put(('blocked', ('Setup could not complete. Check the output and chosen paths; existing data was preserved. Retry after resolving the cause.', None)))
        threading.Thread(target=work, daemon=True).start()

    def finish(self):
        self.busy = False
        self.progress.stop()
        for widget in self.controls + [self.plan_button, self.install_button, self.login_button]:
            widget.configure(state='normal')
        for widget in self.controls[:3]:
            widget.configure(state='readonly')
        self.stop_button.configure(state='disabled')

    def poll(self):
        while not self.events.empty():
            kind, value = self.events.get_nowait()
            if kind == 'output':
                self.write(value)
            elif kind == 'agent-status':
                self.desktop_status.set(value[0])
                self.cli_status.set(value[1])
            elif kind == 'blocked':
                self.finish()
                self.status.set(value[0])
                self.url = value[1]
                self.link_button.configure(text='Open required step', state='normal' if self.url else 'disabled')
            elif kind == 'done':
                self.finish()
                self.status.set(value)
            elif kind == 'result':
                self.finish()
                self.result = value
                self.status.set('Runtime and PDF checks passed. Sign in to your agent and confirm its plan and permissions.')
                self.write('Open the source folder in your desktop agent: ' + value['source'])
                self.write('Grant separate access to: ' + value['workspace'])
                self.write('Your copyable first message is in: ' + value['starter'])
                self.write('Generic improvements: ' + value['feedback'] + '; GitHub: ' + value['feedback_auth'])
                self.url = Path(value['starter']).as_uri()
                self.link_button.configure(text='Open your first-message instructions', state='normal')
                self.copy_button.configure(state='normal')
        self.root.after(100, self.poll)

    def copy_starter(self):
        if self.result:
            text = Path(self.result['starter']).read_text(encoding='utf-8')
            prompt = text.split('Paste this into a new local agent chat:\n\n', 1)[-1].strip()
            self.root.clipboard_clear()
            self.root.clipboard_append(prompt)
            self.status.set('First message copied. Open the source folder in your agent and paste it.')

    def open_step(self):
        if self.url:
            webbrowser.open(self.url)

    def stop(self):
        if self.runner:
            self.status.set('Stop requested. Waiting for the owned operation to finish…')
            threading.Thread(target=self.runner.stop, daemon=True).start()

    def close(self):
        if self.busy:
            self.stop()
            messagebox.showinfo('Stopping setup', 'Wait for the stop result before closing. Native installers may need to finish their own operation.', parent=self.root)
        else:
            self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-test', help='Write a non-installing Tk/bundle smoke result to this file')
    args = parser.parse_args()
    root = tk.Tk()
    wizard = Wizard(root)
    if args.self_test:
        root.withdraw()
        root.update_idletasks()
        result = {'status': 'passed', 'tk': root.tk.call('info', 'patchlevel'),
                  'bundled': bool(getattr(sys, 'frozen', False)), 'widgets': len(wizard.controls),
                  'installs_executed': False}
        Path(args.self_test).write_text(json.dumps(result), encoding='utf-8')
        root.destroy()
    else:
        root.mainloop()


if __name__ == '__main__':
    main()
