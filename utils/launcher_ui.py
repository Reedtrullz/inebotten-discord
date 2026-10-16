"""Shared Tk adapter: widgets and configuration are owned by the main loop."""
from __future__ import annotations

import os
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext

from core.access_policy import describe_access_settings
from core.config_schema import hermes_settings_path, update_settings, validate_settings
from utils.openrouter_models import fetch_openrouter_models
from utils.launcher_runtime import LauncherController, loopback_probe


STATE_LABELS = {
    'starting':'Starter …', 'connecting':'Kobler til …', 'ready':'Tilkoblet og klar',
    'degraded':'Krever oppfølging', 'stopping':'Avslutter …', 'exited':'Avsluttet',
}


class DesktopLauncher:
    def __init__(self, root, *, command, project_root, controller=None, model_fetcher=None):
        self.root=root
        self._main_thread=threading.get_ident()
        self._command=command
        self._project_root=project_root
        self._closing=False
        self._probe_port=8080
        self._model_fetcher=model_fetcher or fetch_openrouter_models
        self._model_results=queue.Queue()
        self._model_fetch_pending=False
        self._model_catalog=()
        self._model_choices={}
        self.controller=controller or LauncherController(probe=lambda nonce:loopback_probe(self._probe_port,nonce))
        root.title('Inebotten')
        root.geometry('720x640')
        root.minsize(480,480)
        root.resizable(True,True)
        self._setup_ui()
        self._load_saved_config()
        self._refresh_model_catalog()
        root.protocol('WM_DELETE_WINDOW',self.close)
        root.bind('<Control-s>',lambda event:self._save_config())
        if os.name!='nt':root.bind('<Command-s>',lambda event:self._save_config())
        self._timer=root.after(100,self._drain)

    @property
    def running(self):
        return self.controller.active

    def _assert_main(self):
        if threading.get_ident()!=self._main_thread:raise RuntimeError('main_thread_required')

    def _setup_ui(self):
        self._assert_main()
        self.root.columnconfigure(0,weight=1)
        self.root.rowconfigure(0,weight=1)
        panes=ttk.Panedwindow(self.root,orient=tk.VERTICAL)
        panes.grid(row=0,column=0,sticky='nsew',padx=16,pady=16)
        config=ttk.LabelFrame(panes,text='Innstillinger',padding=12)
        config.columnconfigure(1,weight=1)
        panes.add(config,weight=1)
        self.provider_var=tk.StringVar(value='lm_studio')
        self.token_var=tk.StringVar()
        self.openrouter_key_var=tk.StringVar()
        self.model_var=tk.StringVar()
        self.model_display_var=tk.StringVar(value='')
        self.free_only_var=tk.BooleanVar(value=False)
        fields=(('AI-tjeneste',self.provider_var,None),('Discord-token',self.token_var,'•'),
                ('OpenRouter-nøkkel',self.openrouter_key_var,'•'),('OpenRouter-modell',self.model_var,None))
        for row,(label,variable,mask) in enumerate(fields):
            ttk.Label(config,text=label).grid(row=row,column=0,sticky='w',padx=(0,12),pady=6)
            if row==0:
                entry=ttk.Combobox(config,textvariable=variable,values=('lm_studio','openrouter'),state='readonly')
                self.provider_combo=entry
                entry.bind('<<ComboboxSelected>>', self._on_provider_change)
            elif row==3:
                model_frame=ttk.Frame(config)
                model_frame.grid(row=row,column=1,sticky='ew',pady=6)
                model_frame.columnconfigure(0,weight=1)
                self.model_combo=ttk.Combobox(
                    model_frame,
                    textvariable=self.model_display_var,
                    values=(),
                    state='disabled'
                )
                self.model_combo.grid(row=0,column=0,sticky='ew')
                self.model_refresh_button=ttk.Button(
                    model_frame,
                    text='Oppdater',
                    command=self._refresh_model_catalog
                )
                self.model_refresh_button.grid(row=0,column=1,padx=(8,0))
                self.model_combo.bind('<<ComboboxSelected>>', self._on_model_selected)
                self.free_only_check=ttk.Checkbutton(
                    model_frame,
                    text='Kun gratis modeller',
                    variable=self.free_only_var,
                    command=self._apply_model_filter,
                )
                self.free_only_check.grid(row=1,column=0,columnspan=2,sticky='w',pady=(6,0))
                continue
            else:
                entry=ttk.Entry(config,textvariable=variable,show=mask or '')
            entry.grid(row=row,column=1,sticky='ew',pady=6)
        ttk.Label(config,text='Tomme nøkkelfelt beholder lagrede nøkler. Modellen må finnes hos tjenesten.',
                  wraplength=430).grid(row=4,column=0,columnspan=2,sticky='w',pady=8)
        controls=ttk.Frame(config)
        controls.grid(row=5,column=0,columnspan=2,sticky='ew',pady=6)
        self.start_button=ttk.Button(controls,text='Start',command=self._start_bot)
        self.start_button.pack(side=tk.LEFT,padx=(0,8))
        self.stop_button=ttk.Button(controls,text='Stopp',command=self._stop_bot,state='disabled')
        self.stop_button.pack(side=tk.LEFT,padx=(0,8))
        ttk.Button(controls,text='Lagre',command=self._save_config).pack(side=tk.RIGHT)
        logs=ttk.LabelFrame(panes,text='Driftslogg',padding=8)
        logs.rowconfigure(0,weight=1);logs.columnconfigure(0,weight=1)
        panes.add(logs,weight=2)
        self.log_text=scrolledtext.ScrolledText(logs,height=12,wrap=tk.WORD,state='disabled')
        self.log_text.grid(row=0,column=0,sticky='nsew')
        self.status_var=tk.StringVar(value=STATE_LABELS['exited'])
        ttk.Label(self.root,textvariable=self.status_var,anchor='w',padding=(16,6)).grid(row=1,column=0,sticky='ew')

    def _log(self,message):
        self._assert_main()
        self.log_text.configure(state='normal')
        self.log_text.insert(tk.END,str(message)[:2048]+'\n')
        # Keep at most 500 lines even during a saturated child-output stream.
        lines=int(self.log_text.index('end-1c').split('.')[0])
        if lines>500:self.log_text.delete('1.0',f'{lines-499}.0')
        self.log_text.see(tk.END)
        self.log_text.configure(state='disabled')

    def _on_provider_change(self, event):
        if self.provider_var.get() == 'openrouter':
            self._refresh_model_catalog()

    def _on_model_selected(self, event):
        self._assert_main()
        selected=self.model_display_var.get()
        self.model_var.set(self._model_choices.get(selected,''))

    def _apply_model_filter(self):
        self._assert_main()
        if not self._model_catalog:
            return
        choices={
            model.choice:model.id
            for model in self._model_catalog
            if not self.free_only_var.get() or model.is_free
        }
        selected=self.model_var.get()
        if selected and not self.free_only_var.get() and selected not in choices.values():
            fallback=f'Lagret modell ({selected})'
            choices[fallback]=selected
        selected_display=next(
            (choice for choice,model_id in choices.items() if model_id==selected),
            '',
        )
        self._model_choices=choices
        self.model_combo.configure(values=tuple(choices))
        self.model_display_var.set(selected_display)

    def _refresh_model_catalog(self):
        self._assert_main()
        if self._closing or self._model_fetch_pending:
            return
        self._model_fetch_pending=True
        self.model_combo.configure(state='disabled')
        self.model_refresh_button.configure(state='disabled')
        self.model_display_var.set('Henter modeller fra OpenRouter …')
        threading.Thread(
            target=self._fetch_model_catalog,
            daemon=True,
            name='inebotten-openrouter-models',
        ).start()

    def _fetch_model_catalog(self):
        try:
            models=self._model_fetcher()
        except Exception:
            self._model_results.put((False, ()))
        else:
            self._model_results.put((True, tuple(models)))

    def _apply_model_catalog(self, succeeded, models):
        self._assert_main()
        self._model_fetch_pending=False
        self.model_refresh_button.configure(state='normal')
        if not succeeded or not models:
            self._model_catalog=()
            self._model_choices={}
            self.model_combo.configure(values=(), state='readonly')
            saved=self.model_var.get()
            self.model_display_var.set(saved or 'Modellene kunne ikke hentes')
            self._log('Kunne ikke hente modeller fra OpenRouter')
            return

        self._model_catalog=tuple(models)
        self._apply_model_filter()
        self.model_combo.configure(state='readonly')
        self._log(f'Hentet {len(models)} modeller fra OpenRouter')

    def _load_saved_config(self):
        try:
            from dotenv import dotenv_values
            values=dotenv_values(hermes_settings_path(),interpolate=False)
            self._log(describe_access_settings(values))
            provider=values.get('AI_PROVIDER')
            model=values.get('OPENROUTER_MODEL')
            if provider:self.provider_var.set(provider)
            if model:self.model_var.set(model)
            port=int(values.get('CONSOLE_PORT') or os.getenv('CONSOLE_PORT','8080'))
            if not 1<=port<=65535:raise ValueError('invalid_console_port')
            self._probe_port=port
        except (OSError,ValueError):self._log('Lagrede innstillinger kunne ikke leses')

    def _create_env_file(self):
        changes={'AI_PROVIDER':self.provider_var.get()}
        for name,variable in (('OPENROUTER_MODEL',self.model_var),('DISCORD_USER_TOKEN',self.token_var),
                              ('OPENROUTER_API_KEY',self.openrouter_key_var)):
            if variable.get():changes[name]=variable.get()
        errors=validate_settings(changes)
        if errors:
            messagebox.showerror('Ugyldige innstillinger','\n'.join(f"{e['field']}: {e['reason']}" for e in errors))
            return False
        try:update_settings(hermes_settings_path(),changes)
        except (OSError,ValueError):
            messagebox.showerror('Lagring mislyktes','Kontroller filtilgang og innstillingsmappe.')
            return False
        self._log('Private innstillinger lagret')
        return True

    def _save_config(self):
        self._assert_main()
        if self.controller.active:
            self._log('Stopp den eide prosessen før innstillingene endres')
            return False
        if not self._create_env_file():return False
        self.token_var.set('');self.openrouter_key_var.set('')
        return True

    def _start_bot(self):
        self._assert_main()
        if self._closing or self.controller.active:return
        if not self._save_config():return
        environment=dict(os.environ)
        environment['HERMES_HOME']=str(hermes_settings_path().parent.parent)
        self.controller.start(self._command(),cwd=str(self._project_root()),env=environment)
        self._apply_state()

    def _stop_bot(self):
        self._assert_main()
        self.controller.stop(time.monotonic()+12)
        self._apply_state()

    def _apply_state(self):
        self._assert_main()
        active=self.controller.active
        self.status_var.set(STATE_LABELS.get(self.controller.state,'Krever oppfølging'))
        self.start_button.configure(state='disabled' if active or self._closing else 'normal')
        self.stop_button.configure(state='normal' if active else 'disabled')

    def _drain(self):
        self._assert_main()
        while True:
            try:
                succeeded,models=self._model_results.get_nowait()
            except queue.Empty:
                break
            self._apply_model_catalog(succeeded,models)
        for event in self.controller.drain(64):
            if event.kind=='log':self._log(event.message)
        self._apply_state()
        if self._closing and not self.controller.active:
            self.root.destroy()
            return
        self._timer=self.root.after(100,self._drain)

    def close(self):
        self._assert_main()
        self._closing=True
        if not self.controller.active:
            self.root.after_cancel(self._timer)
            self.root.destroy()
        else:
            self._stop_bot()
            self._log('Venter på bekreftet avslutning av eide prosesser …')
