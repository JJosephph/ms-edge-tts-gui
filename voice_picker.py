# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText: 2026 WangYufan (QQ 1471056247)
# SPDX-License-Identifier: GPL-3.0-or-later
"""In-app voice picker with a per-row favorite star.

CustomTkinter's combobox is backed by a native Tk menu, which cannot host a
second clickable control per row.  This picker keeps the trigger compact while
the popover is a real CTk surface, so favorites can be toggled without closing
the list or moving focus back to a separate toolbar button.
"""

from __future__ import annotations

import tkinter as tk
from typing import Callable, Iterable, Optional

import customtkinter as ctk


class VoicePicker(ctk.CTkFrame):
    def __init__(
        self,
        master,
        *,
        command: Optional[Callable[[str], None]] = None,
        is_favorite: Optional[Callable[[str], bool]] = None,
        on_toggle_favorite: Optional[Callable[[str], None]] = None,
        font=None,
        text_color: str = "#F2F6FF",
        muted_color: str = "#91A4C3",
        field_color: str = "#0A1322",
        border_color: str = "#263B5C",
        popup_color: str = "#111D31",
        hover_color: str = "#182944",
        accent_color: str = "#5A8CFF",
        star_color: str = "#F6C66C",
        **kwargs,
    ):
        # Our combobox-style API accepts ``values``, but the CTkFrame base
        # does not.  Pull it out before handing the remaining kwargs to
        # CustomTkinter, otherwise startup fails with "unsupported arguments".
        kwargs.pop("values", None)
        super().__init__(master, fg_color="transparent", **kwargs)
        self._command = command
        self._is_favorite = is_favorite or (lambda _value: False)
        self._on_toggle_favorite = on_toggle_favorite
        self._values: list[str] = []
        self._value = ""
        self._state = "normal"
        self._favorite_values: Optional[set[str]] = None
        self._popup: Optional[ctk.CTkToplevel] = None
        self._star_buttons: dict[str, ctk.CTkButton] = {}
        self._font = font
        self._text_color = text_color
        self._muted_color = muted_color
        self._field_color = field_color
        self._border_color = border_color
        self._popup_color = popup_color
        self._hover_color = hover_color
        self._accent_color = accent_color
        self._star_color = star_color

        self.grid_columnconfigure(0, weight=1)
        self._button = ctk.CTkButton(
            self,
            text="",
            height=34,
            anchor="w",
            corner_radius=8,
            fg_color=field_color,
            hover_color=hover_color,
            border_width=1,
            border_color=border_color,
            text_color=text_color,
            font=font,
            command=self._toggle_popup,
        )
        self._button.grid(row=0, column=0, sticky="ew")
        self.bind("<Destroy>", self._on_destroy, add="+")

    def configure(self, require_redraw=False, **kwargs):
        if "values" in kwargs:
            self.set_values(kwargs.pop("values"))
        if "state" in kwargs:
            self.set_state(kwargs.pop("state"))
        if "text_color" in kwargs:
            self._text_color = kwargs.pop("text_color")
            self._button.configure(text_color=self._text_color)
        if "font" in kwargs:
            self._font = kwargs.pop("font")
            self._button.configure(font=self._font)
        return super().configure(require_redraw=require_redraw, **kwargs)

    def cget(self, attribute_name: str):
        if attribute_name == "values":
            return list(self._values)
        if attribute_name == "state":
            return self._state
        return super().cget(attribute_name)

    def set_values(self, values: Iterable[str]):
        self._values = [str(value) for value in values]
        if self._value not in self._values:
            self._value = self._values[0] if self._values else ""
        self._star_buttons.clear()
        self._render_trigger()
        if self._popup is not None:
            self._close_popup()

    def set(self, value: str):
        self._value = str(value)
        self._values = self._values or [self._value]
        self._render_trigger()

    def get(self) -> str:
        return self._value

    def set_state(self, state: str):
        self._state = state
        self._button.configure(state=state)

    def set_favorites(self):
        """Refresh stars without rebuilding the popover under the pointer."""
        self._star_buttons = {
            value: button
            for value, button in self._star_buttons.items()
            if button.winfo_exists()
        }
        for value, button in self._star_buttons.items():
            try:
                button.configure(
                    text="★" if self._row_is_favorite(value) else "☆"
                )
            except tk.TclError:
                pass

    def set_favorite_values(self, values: Iterable[str]):
        """Provide favorites directly so row callbacks stay O(1).

        Re-resolving a display label against the whole catalogue on every
        star click is unnecessary and can select the wrong row when two
        providers expose similar labels.
        """
        self._favorite_values = {str(value) for value in values}

    def _row_is_favorite(self, value: str) -> bool:
        if self._favorite_values is not None:
            return value in self._favorite_values
        return bool(self._is_favorite(value))

    def _render_trigger(self):
        suffix = "  ▾" if self._state != "disabled" else ""
        self._button.configure(text=f"{self._value}{suffix}")

    def _toggle_popup(self):
        if self._popup is not None:
            self._close_popup()
            return
        self._open_popup()

    def _open_popup(self):
        if self._state == "disabled" or not self._values:
            return
        self._close_popup()
        popup = ctk.CTkToplevel(self)
        popup.overrideredirect(True)
        popup.transient(self.winfo_toplevel())
        popup.configure(fg_color=self._popup_color)
        popup.grid_columnconfigure(0, weight=1)
        popup.grid_rowconfigure(0, weight=1)
        popup.bind("<Escape>", lambda _event: self._close_popup())
        popup.bind("<FocusOut>", self._on_popup_focus_out)

        width = max(260, self.winfo_width())
        rows = len(self._values)
        height = min(380, max(64, rows * 42 + 14))
        x = self.winfo_rootx()
        y = self.winfo_rooty() + self.winfo_height() + 4
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        if x + width > screen_w - 8:
            x = max(8, screen_w - width - 8)
        if y + height > screen_h - 8:
            y = max(8, self.winfo_rooty() - height - 4)
        popup.geometry(f"{width}x{height}+{int(x)}+{int(y)}")

        shell = ctk.CTkFrame(
            popup,
            corner_radius=10,
            fg_color=self._popup_color,
            border_width=1,
            border_color=self._border_color,
        )
        shell.grid(row=0, column=0, sticky="nsew", padx=1, pady=1)
        shell.grid_columnconfigure(0, weight=1)
        shell.grid_rowconfigure(0, weight=1)
        listbox = ctk.CTkScrollableFrame(
            shell,
            fg_color=self._popup_color,
            corner_radius=8,
            scrollbar_button_color=self._border_color,
            scrollbar_button_hover_color=self._hover_color,
        )
        listbox.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
        listbox.grid_columnconfigure(0, weight=1)
        self._star_buttons.clear()

        for index, value in enumerate(self._values):
            row = ctk.CTkFrame(
                listbox,
                fg_color=(
                    self._hover_color
                    if value == self._value
                    else "transparent"
                ),
                corner_radius=7,
            )
            row.grid(row=index, column=0, sticky="ew", pady=1)
            row.grid_columnconfigure(0, weight=1)
            label = ctk.CTkLabel(
                row,
                text=value,
                anchor="w",
                justify="left",
                wraplength=max(130, width - 92),
                text_color=self._text_color,
                font=self._font,
            )
            label.grid(row=0, column=0, sticky="ew", padx=(9, 4), pady=7)
            star = ctk.CTkButton(
                row,
                text="★" if self._row_is_favorite(value) else "☆",
                width=30,
                height=28,
                corner_radius=7,
                fg_color="transparent",
                hover_color=self._hover_color,
                text_color=self._star_color,
                font=self._font,
                command=lambda v=value: self._toggle_row_favorite(v),
            )
            star.grid(row=0, column=1, padx=(0, 5), pady=4)
            self._star_buttons[value] = star
            for widget in (row, label):
                widget.configure(cursor="hand2")
                widget.bind("<Button-1>", lambda _event, v=value: self._choose(v))
            row.bind(
                "<Enter>",
                lambda _event, w=row: w.configure(fg_color=self._hover_color),
            )
            row.bind(
                "<Leave>",
                lambda _event, w=row, v=value: w.configure(
                    fg_color=(
                        self._hover_color
                        if v == self._value
                        else "transparent"
                    )
                ),
            )

        self._popup = popup
        popup.lift()
        popup.focus_force()

    def _toggle_row_favorite(self, value: str):
        if self._on_toggle_favorite is not None:
            self._on_toggle_favorite(value)
        self.set_favorites()

    def _choose(self, value: str):
        self._value = value
        self._render_trigger()
        self._close_popup()
        if self._command is not None:
            self._command(value)

    def _on_popup_focus_out(self, _event=None):
        if self._popup is None:
            return
        self.after(120, self._close_if_unfocused)

    def _close_if_unfocused(self):
        popup = self._popup
        if popup is None:
            return
        try:
            focused = self.focus_get()
        except (KeyError, tk.TclError):
            focused = None
        if focused is None or not str(focused).startswith(str(popup)):
            self._close_popup()

    def _close_popup(self):
        popup = self._popup
        self._popup = None
        self._star_buttons.clear()
        if popup is not None:
            try:
                popup.destroy()
            except tk.TclError:
                pass

    def _on_destroy(self, _event=None):
        self._close_popup()
