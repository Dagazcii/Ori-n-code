#!/usr/bin/env python3
"""Orion Code TUI — live tools, streaming, file panel, progress."""
from __future__ import annotations

import gc
import os
import sys
from pathlib import Path

try:
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Horizontal, Vertical
    from textual.widgets import (
        Footer,
        Input,
        ProgressBar,
        RichLog,
        Static,
    )
    from textual import work
except ImportError as e:
    print("Textual is not installed. Run: pip install textual")
    print(e)
    sys.exit(1)

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import orion_code as oc

COMMAND_HELP = """
[bold]Commands[/]
  [cyan]/[/]  /config  /git  /proyecto  /compact  /red  /clear
  /diario  /backup  /fichas  /model  /save  /load  /quit
  [cyan]@file[/]  ·  [cyan]Ctrl+S[/] SVG
  [cyan]PgUp/PgDn[/] scroll chat  ·  [cyan]End[/] jump to latest
"""


class OrionTUI(App):
    CSS = """
    Screen { layout: vertical; }
    #brand {
        height: 3;
        padding: 0 1;
        background: $surface;
        color: $accent;
        text-style: bold;
    }
    #body { height: 1fr; }
    #chat {
        height: 1fr;
        border: solid $primary;
        padding: 0 1;
    }
    #progress-row { height: 1; padding: 0 1; }
    #status {
        height: 1;
        padding: 0 1;
        background: $surface;
        color: $text-muted;
    }
    #hint {
        height: auto;
        max-height: 6;
        padding: 0 1;
        background: $boost;
        display: none;
    }
    #hint.visible { display: block; }
    #input { margin: 0 1 1 1; }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit"),
        Binding("ctrl+q", "quit", "Quit"),
        Binding("f1", "help", "Help"),
        Binding("ctrl+s", "save_svg", "SVG"),
        Binding("pageup", "scroll_up", "Up", show=False),
        Binding("pagedown", "scroll_down", "Down", show=False),
        Binding("end", "scroll_end", "End", show=False),
    ]

    def __init__(self, api_key: str, model: str):
        super().__init__()
        self.api_key = api_key
        self.model = model
        oc._API_KEY_REF["key"] = api_key
        oc._API_KEY_REF["model"] = model
        try:
            oc.restore_brain_from_backup_if_empty()
        except Exception:
            pass
        self.brain = oc.OrionBrain()
        try:
            pkg_soul = Path(oc.__file__).resolve().parent / "soul_default.md"
            if pkg_soul.exists() and (
                not oc.SOUL_PATH.exists() or len(self.brain.read_soul()) < 40
            ):
                self.brain.write_soul(pkg_soul.read_text(encoding="utf-8"))
        except Exception:
            pass
        history, saved_at = oc.auto_load_history()
        self.history = oc.sanitize_history(history)
        self.system = oc.build_system(self.brain)
        self.saved_at = saved_at
        self._busy = False
        self._config_step: str | None = None
        self._stream_open = False

    def compose(self) -> ComposeResult:
        agent = oc.agent_label()
        yield Static(
            f"  {agent} Code  ·  Dagazcii Dev  ·  {self.model}",
            id="brand",
        )
        with Vertical(id="body"):
            yield RichLog(id="chat", highlight=True, markup=True, wrap=True)
            with Horizontal(id="progress-row"):
                yield ProgressBar(total=100, show_eta=False, id="prog")
            yield Static(id="hint")
            yield Static("", id="status")
            yield Input(placeholder="Type / for commands…", id="input")
        yield Footer()

    def on_mount(self) -> None:
        # UI hooks for live shell + stream
        oc.UI_HOOKS["shell_line"] = self._hook_shell
        oc.UI_HOOKS["stream_token"] = self._hook_stream
        oc.UI_HOOKS["progress"] = self._hook_progress

        prog = self.query_one("#prog", ProgressBar)
        prog.update(total=100, progress=0)

        chat = self.query_one("#chat", RichLog)
        chat.write("[bold cyan]Orion Code TUI[/] — PgUp/PgDn scroll · End latest")
        if self.history:
            chat.write(
                f"[dim]Session restored ({self.saved_at}), "
                f"messages: {len(self.history)}[/]"
            )
        try:
            open_line = oc.proactive_open_line(self.brain, self.history)
        except Exception:
            open_line = "Ready. What do you need?"
        chat.write(f"[bold green]{oc.agent_label()}:[/] {open_line}")
        if not self.history:
            self.history.append(
                {"role": "user", "parts": [{"text": "(session start)"}]}
            )
        self.history.append({"role": "model", "parts": [{"text": open_line}]})
        self.history = oc.ensure_api_history(self.history)
        oc.auto_save_history(self.history)
        self._refresh_status()
        self.query_one("#input", Input).focus()

    def on_unmount(self) -> None:
        oc.UI_HOOKS.clear()

    def _hook_shell(self, line: str) -> None:
        def _w() -> None:
            self.query_one("#chat", RichLog).write(f"[dim]{line}[/]")
            self.query_one("#chat", RichLog).scroll_end(animate=False)
        try:
            self.call_from_thread(_w)
        except RuntimeError:
            _w()

    def _hook_stream(self, token: str) -> None:
        def _w() -> None:
            chat = self.query_one("#chat", RichLog)
            if not self._stream_open:
                chat.write(f"[bold green]{oc.agent_label()}:[/] ", scroll_end=False)
                self._stream_open = True
            # RichLog has no true token append; write small chunks
            chat.write(token.replace("\n", "\\n") if False else token)
            chat.scroll_end(animate=False)
            prog = self.query_one("#prog", ProgressBar)
            prog.advance(1)
            if prog.progress >= 95:
                prog.update(progress=30)
        try:
            self.call_from_thread(_w)
        except RuntimeError:
            _w()

    def _hook_progress(self, state: str) -> None:
        def _w() -> None:
            prog = self.query_one("#prog", ProgressBar)
            if state == "running":
                prog.update(progress=15)
            elif state == "idle":
                prog.update(progress=100)
            else:
                prog.advance(5)
        try:
            self.call_from_thread(_w)
        except RuntimeError:
            _w()

    def _refresh_status(self) -> None:
        cwd = os.getcwd()
        if len(cwd) > 36:
            cwd = "…" + cwd[-35:]
        branch = ""
        try:
            import subprocess

            r = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True,
                text=True,
                timeout=4,
            )
            if r.returncode == 0:
                branch = f" · git:{r.stdout.strip()}"
        except Exception:
            pass
        http = "httpx" if oc.USE_HTTPX else ("requests" if oc.USE_REQUESTS else "urllib")
        self.query_one("#status", Static).update(
            f" {self.model} · {cwd}{branch} · {http}"
        )

    def _chat(self, msg: str) -> None:
        log = self.query_one("#chat", RichLog)
        log.write(msg)
        log.scroll_end(animate=False)

    def _show_hint(self, text: str) -> None:
        hint = self.query_one("#hint", Static)
        hint.update(text)
        hint.add_class("visible")

    def _hide_hint(self) -> None:
        hint = self.query_one("#hint", Static)
        hint.update("")
        hint.remove_class("visible")

    def action_help(self) -> None:
        self._chat(COMMAND_HELP)

    def action_quit(self) -> None:
        oc.auto_save_history(self.history)
        try:
            self.brain.save()
        except Exception:
            pass
        oc.UI_HOOKS.clear()
        self.exit()


    def action_scroll_up(self) -> None:
        self.query_one("#chat", RichLog).scroll_page_up(animate=False)

    def action_scroll_down(self) -> None:
        self.query_one("#chat", RichLog).scroll_page_down(animate=False)

    def action_scroll_end(self) -> None:
        self.query_one("#chat", RichLog).scroll_end(animate=False)

    def action_save_svg(self) -> None:
        candidates = [
            Path.home() / "storage" / "shared" / "Download",
            Path.home() / "storage" / "downloads",
            Path("/storage/emulated/0/Download"),
            Path.home() / ".orion-code",
            Path.cwd(),
        ]
        folder = None
        for c in candidates:
            try:
                c.mkdir(parents=True, exist_ok=True)
                if c.is_dir():
                    folder = c
                    break
            except Exception:
                continue
        if folder is None:
            self._chat("[red]No writable folder for SVG.[/]")
            return
        from datetime import datetime

        path = folder / f"orion-tui-{datetime.now().strftime('%Y%m%d-%H%M%S')}.svg"
        try:
            self.save_screenshot(filename=str(path))
            self._chat(f"[green]SVG saved:[/] {path}")
        except Exception as e:
            self._chat(f"[yellow]SVG failed: {e}[/]")



    def on_input_changed(self, event: Input.Changed) -> None:
        if self._config_step:
            return
        val = event.value or ""
        if val == "/":
            self._show_hint(
                " /config /git /proyecto /compact /red /clear "
                "/diario /backup /fichas /model /save /load /quit"
            )
        elif val.startswith("/") and len(val) < 24:
            all_c = [
                "/config", "/git", "/proyecto", "/compact", "/red", "/clear",
                "/diario", "/backup", "/fichas", "/mood", "/model", "/save",
                "/load", "/sessions", "/quit", "/help",
            ]
            matches = [c for c in all_c if c.startswith(val.lower())]
            if matches:
                self._show_hint(" " + "  ".join(matches))
            else:
                self._hide_hint()
        else:
            self._hide_hint()

    def _start_config_wizard(self) -> None:
        self._config_step = "menu"
        cfg = oc.load_config()
        user_name = cfg.get("user_name") or "(not set)"
        agent_name = cfg.get("agent_name") or "Orion"
        model = cfg.get("model") or oc.DEFAULT_MODEL
        auto = "on" if cfg.get("auto_mode", True) else "off"
        key_set = bool(
            os.environ.get("GEMINI_API_KEY")
            or os.environ.get("GOOGLE_API_KEY")
            or (Path.cwd() / ".env").exists()
        )
        self._chat(
            "[bold]Configuration[/]\n"
            f"  [cyan]1[/] Your name     {user_name}\n"
            f"  [cyan]2[/] Agent name    {agent_name}\n"
            f"  [cyan]3[/] Model         {model}\n"
            f"  [cyan]4[/] Auto mode     {auto}\n"
            f"  [cyan]5[/] API key       {'set' if key_set else 'not set'}\n"
            f"  [cyan]0[/] Back\n"
            "[dim]Choose 0-5[/]"
        )
        self.query_one("#input", Input).placeholder = "Config: choose 0-5"

    def _handle_config_step(self, text: str) -> bool:
        if not self._config_step:
            return False
        step = self._config_step
        t = text.strip()
        if step == "menu":
            if t in ("0", "q", "quit", "back", ""):
                self._config_step = None
                self.query_one("#input", Input).placeholder = "Type / for commands…"
                self._chat("[dim]Config closed.[/]")
                return True
            if t == "1":
                self._config_step = "user_name"
                self._chat("[dim]Enter your name:[/]")
                return True
            if t == "2":
                self._config_step = "agent_name"
                self._chat("[dim]Enter agent name:[/]")
                return True
            if t == "3":
                self._config_step = "model"
                self._chat("[dim]Enter model name:[/]")
                return True
            if t == "4":
                self._config_step = "auto"
                self._chat("[dim]Auto mode: on or off[/]")
                return True
            if t == "5":
                self._config_step = "key_menu"
                self._chat("[dim]a) Set key  b) Clear  c) Cancel[/]")
                return True
            self._chat("[yellow]Choose 0-5[/]")
            return True
        if step == "user_name":
            if t:
                oc.set_pref("user_name", t)
                self._chat(f"[green]user_name = {t}[/]")
            self._start_config_wizard()
            return True
        if step == "agent_name":
            if t:
                oc.set_pref("agent_name", t)
                self._chat(f"[green]agent_name = {t}[/]")
            self.system = oc.build_system(self.brain)
            self._start_config_wizard()
            return True
        if step == "model":
            if t:
                oc.set_pref("model", t)
                oc._API_KEY_REF["model"] = t
                self.model = t
                self._chat(f"[green]model = {t}[/]")
                self._refresh_status()
            self._start_config_wizard()
            return True
        if step == "auto":
            low = t.lower()
            if low in ("on", "1", "true", "si", "sí"):
                oc.set_pref("auto_mode", True)
                self._chat("[green]auto_mode = on[/]")
            elif low in ("off", "0", "false", "no"):
                oc.set_pref("auto_mode", False)
                self._chat("[green]auto_mode = off[/]")
            self._start_config_wizard()
            return True
        if step == "key_menu":
            if t.lower() == "a":
                self._config_step = "key_set"
                self._chat("[dim]Paste API key:[/]")
                return True
            if t.lower() == "b":
                if "GEMINI_API_KEY" in os.environ:
                    del os.environ["GEMINI_API_KEY"]
                oc.clear_api_key_file()
                self._chat("[green]API key cleared[/]")
                self._start_config_wizard()
                return True
            self._start_config_wizard()
            return True
        if step == "key_set":
            if t:
                os.environ["GEMINI_API_KEY"] = t
                path = oc.save_api_key_to_env(t)
                oc._API_KEY_REF["key"] = t
                self.api_key = t
                self._chat(f"[green]API key saved ({path})[/]")
            self._start_config_wizard()
            return True
        self._config_step = None
        return False

    def _run_slash_command(self, text: str) -> bool:
        low = text.lower().strip()
        parts = text.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        if text.strip() == "/" or low in ("/help", "/ayuda", "/comandos", "/menu"):
            self.action_help()
            return True
        if low in ("/quit", "/exit", "/salir"):
            self.action_quit()
            return True
        if low in ("/clear", "/limpiar"):
            self.history.clear()
            self.query_one("#chat", RichLog).clear()
            self._chat("[dim]Chat cleared.[/]")
            return True
        if low in ("/proyecto", "/project", "/ctx"):
            self._chat(oc.snapshot_project_brief(Path.cwd()))
            return True
        if low in ("/red", "/net", "/internet"):
            ok = oc.network_reachable()
            http = "httpx" if oc.USE_HTTPX else ("requests" if oc.USE_REQUESTS else "urllib")
            self._chat(f"HTTP: {http}\n{'Online.' if ok else 'Offline.'}")
            return True
        if low in ("/compact", "/compactar"):
            before = len(self.history)
            self.history = oc.compact_history(self.history, keep_last=10)
            oc.auto_save_history(self.history)
            self._chat(f"[dim]Compacted {before} → {len(self.history)}[/]")
            return True
        if low in ("/diario", "/diary"):
            if oc.DIARY_PATH.exists():
                self._chat(
                    oc.DIARY_PATH.read_text(encoding="utf-8", errors="replace")[-8000:]
                )
            else:
                self._chat("(empty diary)")
            return True
        if low in ("/backup", "/respaldo"):
            try:
                self.brain.save()
            except Exception:
                pass
            self._chat(str(oc.backup_brain_files()))
            return True
        if low in ("/fichas", "/cards", "/gustos", "/promesas", "/proyectos"):
            try:
                self._chat(self.brain.cards_text())
            except Exception as e:
                self._chat(str(e))
            return True
        if low in ("/mood", "/animo", "/brain", "/cerebro"):
            try:
                self._chat(self.brain.status_text())
            except Exception as e:
                self._chat(str(e))
            return True
        if low in ("/soul", "/alma"):
            try:
                self._chat(self.brain.read_soul())
            except Exception as e:
                self._chat(str(e))
            return True
        if cmd in ("/model", "/modelo"):
            if arg:
                oc.save_model(arg)
                self.model = arg
                oc._API_KEY_REF["model"] = arg
                self._chat(f"[green]Model: {arg}[/]")
                self._refresh_status()
            else:
                self._chat(f"Current: {self.model}")
            return True
        if cmd in ("/save", "/guardar"):
            import datetime

            name = arg or datetime.datetime.now().strftime("chat_%Y%m%d_%H%M")
            self._chat(oc.session_save(name, self.history))
            return True
        if cmd in ("/load", "/cargar"):
            if not arg:
                self._chat("Usage: /load name")
                return True
            data, msg = oc.session_load(arg)
            self._chat(msg)
            if data is not None:
                self.history = data
            return True
        if low in ("/sessions", "/sesiones"):
            self._chat(oc.session_list())
            return True
        if cmd == "/git" or low == "/git":
            sub = arg.lower()
            if not sub or sub in ("status", "st"):
                self._chat(oc.tool_git_status())
            elif sub in ("diff", "d"):
                self._chat(oc.tool_git_diff(False))
            elif sub in ("log", "l"):
                self._chat(oc.tool_git_log(10))
            elif sub.startswith("add"):
                paths = arg.split(None, 1)
                self._chat(oc.tool_git_add(paths[1] if len(paths) > 1 else ".", True))
            elif sub.startswith("commit "):
                msg = arg.split(None, 1)
                if len(msg) < 2:
                    self._chat("Usage: /git commit <message>")
                else:
                    self._chat(oc.tool_git_commit(msg[1], confirm=True))
            elif sub in ("push",):
                self._chat(oc.tool_git_push(confirm=True))
            elif sub in ("pull",):
                self._chat(oc.tool_git_pull(confirm=True))
            elif sub in ("remote",):
                self._chat(oc.tool_git_remote("list"))
            else:
                self._chat(
                    "Usage: /git status|diff|log|add|commit|push|pull|remote\n"
                    "Auth: export GITHUB_TOKEN=your_pat"
                )
            return True
        if cmd == "/config" or low == "/config":
            if arg:
                msg = oc.apply_config_command(arg, oc._API_KEY_REF)
                if msg:
                    self._chat(f"[green]{msg}[/]")
                if oc._API_KEY_REF.get("model"):
                    self.model = oc._API_KEY_REF["model"]
                if oc._API_KEY_REF.get("key"):
                    self.api_key = oc._API_KEY_REF["key"]
                self.system = oc.build_system(self.brain)
                self._refresh_status()
            else:
                self._start_config_wizard()
            return True
        if text.startswith("/"):
            self._chat("[yellow]Unknown command. Type / for help.[/]")
            return True
        return False

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = (event.value or "").strip()
        event.input.value = ""
        self._hide_hint()
        if not text:
            return
        if self._busy:
            if text.lower() in ("/cancel", "/stop", "cancel"):
                self._busy = False
                self._chat("[yellow]Marked idle. Previous task may still finish in background.[/]")
                try:
                    self.query_one("#prog", ProgressBar).update(progress=0)
                except Exception:
                    pass
            else:
                self._chat("[dim]Busy… wait or type /cancel[/]")
            return
        if self._handle_config_step(text):
            return
        if self._run_slash_command(text):
            return
        self._chat(f"[bold blue]you>[/] {text}")
        self._busy = True
        self._stream_open = False
        prog = self.query_one("#prog", ProgressBar)
        prog.update(total=100, progress=5)
        self._chat("[dim]… thinking (type /cancel if stuck)[/]")
        self._worker_turn(text)

    @work(thread=True, exclusive=True)
    def _worker_turn(self, text: str) -> None:
        try:
            display: list[str] = []
            expanded = oc.expand_at_mentions(text)
            if expanded != text:
                display.append("[dim](@ path resolved)[/]")
            user_parts = [{"text": oc.redact_secrets(expanded)}]
            try:
                self.brain.perceive(text)
                self.system = oc.build_system(self.brain)
            except Exception:
                pass
            self.history = oc.sanitize_history(self.history)
            self.history.append({"role": "user", "parts": user_parts})

            # Try text stream for simple chat
            streamed_ok = False
            if oc.should_try_text_stream(text):
                try:
                    self.call_from_thread(
                        lambda: self.query_one("#prog", ProgressBar).update(progress=20)
                    )
                    streamed = oc.gemini_stream_text(
                        self.api_key,
                        self.model,
                        oc.ensure_api_history(self.history),
                        self.system,
                    )
                    if streamed and streamed.strip():
                        self.history.append(
                            {"role": "model", "parts": [{"text": streamed}]}
                        )
                        streamed_ok = True
                        # tokens already shown via hook
                except Exception as ex:
                    display.append(f"[dim](stream fallback: {ex})[/]")

            if not streamed_ok:
                for _ in range(40):
                    if len(self.history) > 14:
                        self.history = oc.compact_history(self.history, keep_last=10)
                    api_hist = oc.ensure_api_history(self.history)
                    try:
                        resp = oc.gemini_generate(
                            self.api_key, self.model, api_hist, self.system
                        )
                    except Exception as e:
                        display.append(f"[red]{e}[/]")
                        break
                    parts = oc.extract_parts(resp)
                    if not parts:
                        display.append("[yellow](empty response)[/]")
                        break
                    fcalls = oc.parts_function_calls(parts)
                    answer = oc.parts_text(parts)
                    if not fcalls:
                        self.history.append({"role": "model", "parts": parts})
                        if answer:
                            display.append(
                                f"[bold green]{oc.agent_label()}:[/] "
                                f"{oc.redact_secrets(answer)}"
                            )
                        break
                    self.history.append({"role": "model", "parts": parts})
                    fn_responses = []
                    for fc in fcalls:
                        name = fc.get("name", "")
                        args = fc.get("args") or {}
                        display.append(f"[dim]  → {name}({args})[/]")
                        # show tool header immediately
                        self.call_from_thread(
                            lambda n=name, a=args: self._chat(
                                f"[dim]  → {n}({a})[/]"
                            )
                        )
                        impl = oc.TOOL_IMPL.get(name)
                        try:
                            result = impl(args) if impl else f"Unknown: {name}"
                        except Exception as ex:
                            result = f"Tool error: {ex}"
                        if not isinstance(
                            result, (str, dict, list, int, float, bool)
                        ):
                            result = str(result)
                        if isinstance(result, str) and len(result) > 8000:
                            result = result[:8000] + "\n...[truncated]"
                        fn_responses.append(
                            {
                                "functionResponse": {
                                    "name": name,
                                    "response": {"result": result},
                                }
                            }
                        )
                    self.history.append({"role": "user", "parts": fn_responses})
                else:
                    display.append("[yellow](tool step limit)[/]")

            self.history = oc.sanitize_history(self.history)
            oc.auto_save_history(self.history)
            try:
                self.brain.save()
            except Exception:
                pass
            self.call_from_thread(self._finish_turn, display, streamed_ok)
        except Exception as e:
            try:
                self.call_from_thread(
                    self._finish_turn, [f"[red]Error: {e}[/]"], False
                )
            except RuntimeError:
                self._finish_turn([f"[red]Error: {e}[/]"], False)

    def _finish_turn(self, lines: list[str], streamed: bool = False) -> None:
        # if streamed, skip duplicate Orion text lines
        for line in lines:
            if streamed and line.startswith(f"[bold green]{oc.agent_label()}"):
                continue
            if line.startswith("[dim]  → ") and streamed:
                continue
            # tool headers may already be live
            if line.startswith("[dim]  → "):
                continue
            self._chat(line)
        self._stream_open = False
        self._busy = False
        prog = self.query_one("#prog", ProgressBar)
        prog.update(progress=100)
        inp = self.query_one("#input", Input)
        try:
            inp.disabled = False
        except Exception:
            pass
        inp.focus()
        self._refresh_status()
        try:
            gc.collect()
        except Exception:
            pass


def main(api_key: str | None = None, model: str | None = None) -> None:
    if not api_key:
        api_key = oc.load_api_key()
    if not model:
        model = oc.load_saved_model(oc.DEFAULT_MODEL)
    app = OrionTUI(api_key, model)
    app.run()


if __name__ == "__main__":
    main()
