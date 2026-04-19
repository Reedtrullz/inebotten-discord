#!/usr/bin/env python3
"""
Inebotten Discord Bot - Windows Launcher
Simple GUI application for Windows users
"""

import os
import sys
import subprocess
import threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext

class InebottenLauncher:
    """Simple GUI launcher for Inebotten Discord Bot"""
    
    def __init__(self, root):
        self.root = root
        self.root.title("Inebotten Discord Bot")
        self.root.geometry("600x500")
        self.root.resizable(False, False)
        
        # Set Windows icon if available
        try:
            self.root.iconbitmap('icon.ico')
        except:
            pass  # Icon not required
        
        # Bot process
        self.bot_process = None
        self.running = False
        
        # Setup UI
        self._setup_ui()
        self._load_saved_config()
    
    def _setup_ui(self):
        """Setup the user interface"""
        # Title
        title_frame = ttk.Frame(self.root, padding="20")
        title_frame.pack(fill=tk.X)
        
        title_label = ttk.Label(
            title_frame,
            text="🤖 Inebotten Discord Bot",
            font=("Segoe UI", 18, "bold")
        )
        title_label.pack()
        
        subtitle_label = ttk.Label(
            title_frame,
            text="Norwegian Discord selfbot with AI integration",
            font=("Segoe UI", 10),
            foreground="gray"
        )
        subtitle_label.pack(pady=(5, 0))
        
        # Configuration Frame
        config_frame = ttk.LabelFrame(self.root, text="Configuration", padding="20")
        config_frame.pack(fill=tk.X, padx=20, pady=10)
        
        # AI Provider Selection
        provider_frame = ttk.Frame(config_frame)
        provider_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(provider_frame, text="AI Provider:").pack(side=tk.LEFT)
        
        self.provider_var = tk.StringVar(value="lm_studio")
        provider_combo = ttk.Combobox(
            provider_frame,
            textvariable=self.provider_var,
            values=["lm_studio", "openrouter"],
            state="readonly",
            width=15
        )
        provider_combo.pack(side=tk.RIGHT)
        
        # Discord Token
        token_frame = ttk.Frame(config_frame)
        token_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(token_frame, text="Discord Token:").pack(anchor=tk.W)
        
        self.token_var = tk.StringVar()
        token_entry = ttk.Entry(token_frame, textvariable=self.token_var, show="•")
        token_entry.pack(fill=tk.X, pady=(5, 0))
        
        # OpenRouter API Key
        self.openrouter_frame = ttk.Frame(config_frame)
        self.openrouter_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(self.openrouter_frame, text="OpenRouter API Key:").pack(anchor=tk.W)
        
        self.openrouter_key_var = tk.StringVar()
        openrouter_entry = ttk.Entry(
            self.openrouter_frame,
            textvariable=self.openrouter_key_var,
            show="•"
        )
        openrouter_entry.pack(fill=tk.X, pady=(5, 0))
        
        # Model Selection
        model_frame = ttk.Frame(config_frame)
        model_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(model_frame, text="Model:").pack(anchor=tk.W)
        
        self.model_var = tk.StringVar(value="google/gemma-3-4b-it:free")
        model_combo = ttk.Combobox(
            model_frame,
            textvariable=self.model_var,
            values=[
                "google/gemma-3-4b-it:free",
                "meta-llama/llama-3-8b-instruct:free",
                "mistralai/mistral-7b-instruct:free",
                "anthropic/claude-3-haiku",
                "openai/gpt-3.5-turbo",
                "openai/gpt-4",
            ],
            state="readonly",
            width=40
        )
        model_combo.pack(fill=tk.X, pady=(5, 0))
        
        # Bind provider change to show/hide OpenRouter fields
        provider_combo.bind("<<ComboboxSelected>>", self._on_provider_change)
        
        # Control Buttons
        button_frame = ttk.Frame(self.root, padding="20")
        button_frame.pack(fill=tk.X)
        
        self.start_button = ttk.Button(
            button_frame,
            text="▶ Start Bot",
            command=self._start_bot,
            width=20
        )
        self.start_button.pack(side=tk.LEFT, padx=(0, 10))
        
        self.stop_button = ttk.Button(
            button_frame,
            text="⏹ Stop Bot",
            command=self._stop_bot,
            state="disabled",
            width=20
        )
        self.stop_button.pack(side=tk.LEFT, padx=(0, 10))
        
        ttk.Button(
            button_frame,
            text="💾 Save Config",
            command=self._save_config,
            width=15
        ).pack(side=tk.RIGHT)
        
        # Output Log
        log_frame = ttk.LabelFrame(self.root, text="Output Log", padding="10")
        log_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 20))
        
        self.log_text = scrolledtext.ScrolledText(
            log_frame,
            height=10,
            font=("Consolas", 9),
            wrap=tk.WORD
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)
        
        # Status Bar
        self.status_var = tk.StringVar(value="Ready")
        status_bar = ttk.Label(
            self.root,
            textvariable=self.status_var,
            relief=tk.SUNKEN,
            anchor=tk.W
        )
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)
        
        # Initial UI state
        self._on_provider_change(None)
    
    def _on_provider_change(self, event):
        """Handle provider selection change"""
        provider = self.provider_var.get()
        
        if provider == "openrouter":
            self.openrouter_frame.pack(fill=tk.X, pady=(0, 10))
            self.openrouter_frame.pack_info()  # Force pack
        else:
            self.openrouter_frame.pack_forget()
    
    def _log(self, message):
        """Add message to log"""
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.root.update_idletasks()
    
    def _load_saved_config(self):
        """Load saved configuration"""
        config_path = Path.home() / ".hermes" / "discord" / "launcher_config.json"
        
        if config_path.exists():
            try:
                import json
                with open(config_path, "r") as f:
                    config = json.load(f)
                
                self.provider_var.set(config.get("provider", "lm_studio"))
                self.token_var.set(config.get("discord_token", ""))
                self.openrouter_key_var.set(config.get("openrouter_key", ""))
                self.model_var.set(config.get("model", "google/gemma-3-4b-it:free"))
                
                self._log("Loaded saved configuration")
            except Exception as e:
                self._log(f"Error loading config: {e}")
    
    def _save_config(self):
        """Save configuration"""
        config_path = Path.home() / ".hermes" / "discord" / "launcher_config.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            import json
            config = {
                "provider": self.provider_var.get(),
                "discord_token": self.token_var.get(),
                "openrouter_key": self.openrouter_key_var.get(),
                "model": self.model_var.get(),
            }
            
            with open(config_path, "w") as f:
                json.dump(config, f, indent=2)
            
            messagebox.showinfo("Success", "Configuration saved!")
            self._log("Configuration saved")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save config: {e}")
    
    def _start_bot(self):
        """Start the Discord bot"""
        # Validate inputs
        if not self.token_var.get():
            messagebox.showerror("Error", "Please enter your Discord token")
            return
        
        if self.provider_var.get() == "openrouter" and not self.openrouter_key_var.get():
            messagebox.showerror("Error", "Please enter your OpenRouter API key")
            return
        
        # Save config first
        self._save_config()
        
        # Create .env file
        self._create_env_file()
        
        # Start bot in background thread
        self.running = True
        self.start_button.config(state="disabled")
        self.stop_button.config(state="normal")
        self.status_var.set("Starting bot...")
        
        thread = threading.Thread(target=self._run_bot, daemon=True)
        thread.start()
    
    def _stop_bot(self):
        """Stop the Discord bot"""
        self.running = False
        self.status_var.set("Stopping bot...")
        
        if self.bot_process:
            try:
                self.bot_process.terminate()
                self._log("Bot stopped")
            except Exception as e:
                self._log(f"Error stopping bot: {e}")
        
        self.start_button.config(state="normal")
        self.stop_button.config(state="disabled")
        self.status_var.set("Ready")
    
    def _create_env_file(self):
        """Create .env file from GUI inputs"""
        env_path = Path.home() / ".hermes" / "discord" / ".env"
        env_path.parent.mkdir(parents=True, exist_ok=True)
        
        env_content = f"""# Discord Selfbot Configuration
DISCORD_USER_TOKEN={self.token_var.get()}

# AI Provider Selection
AI_PROVIDER={self.provider_var.get()}

# LM Studio Configuration
HERMES_API_URL=http://127.0.0.1:3000/api/chat
HERMES_TEMPERATURE=0.7
HERMES_MAX_TOKENS=200

# OpenRouter Configuration
OPENROUTER_API_KEY={self.openrouter_key_var.get()}
OPENROUTER_MODEL={self.model_var.get()}
OPENROUTER_TEMPERATURE=0.7
OPENROUTER_MAX_TOKENS=200
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1

# Rate Limiting
MAX_MSGS_PER_SEC=5
DAILY_QUOTA=10000
SAFE_INTERVAL=1
POLL_INTERVAL=8
"""
        
        with open(env_path, "w") as f:
            f.write(env_content)
        
        self._log(f"Created .env file at {env_path}")
    
    def _run_bot(self):
        """Run the bot in background thread"""
        try:
            # Get the script directory
            script_dir = Path(__file__).parent.parent
            
            # Run the bot
            self.bot_process = subprocess.Popen(
                [sys.executable, str(script_dir / "run_both.py")],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True,
                cwd=str(script_dir),
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
            )
            
            self._log("Bot started successfully")
            self.status_var.set("Bot running")
            
            # Stream output
            while self.running:
                line = self.bot_process.stdout.readline()
                if line:
                    self._log(line.rstrip())
                else:
                    break
            
            # Process ended
            return_code = self.bot_process.poll()
            self._log(f"Bot exited with code: {return_code}")
            
            if return_code == 0:
                self.status_var.set("Bot stopped")
            else:
                self.status_var.set(f"Bot error (code {return_code})")
            
        except Exception as e:
            self._log(f"Error running bot: {e}")
            self.status_var.set("Error")
        finally:
            self.running = False
            self.start_button.config(state="normal")
            self.stop_button.config(state="disabled")


def main():
    """Main entry point"""
    root = tk.Tk()
    app = InebottenLauncher(root)
    
    # Handle window close
    def on_closing():
        if app.running:
            if messagebox.askokcancel("Quit", "Bot is still running. Stop it?"):
                app._stop_bot()
                root.after(1000, root.destroy)
        else:
            root.destroy()
    
    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()


if __name__ == "__main__":
    main()
