# meikipop/gui/popup.py
import logging
import html
import time
import threading
from typing import List, Optional

from PyQt6.QtCore import QTimer, QPoint, QSize, pyqtSignal
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QCursor, QFont, QFontMetrics, QFontInfo
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QFrame, QApplication

from meikipop.config.config import config, IS_MACOS
from meikipop.dictionary.lookup import DictionaryEntry, KanjiEntry
from meikipop.gui.magpie_manager import magpie_manager

# macOS-specific imports for focus management
if IS_MACOS:
    try:
        import Quartz
    except ImportError:
        Quartz = None

logger = logging.getLogger(__name__)
USER_GLOSS_LIMIT = 300  # extra dictionaries can carry whole encyclopedia paragraphs


class Popup(QWidget):
    mining_finished = pyqtSignal(bool, str)
    def __init__(self, shared_state, input_loop):
        super().__init__()
        self._latest_data = None
        self._last_latest_data = None
        self._data_lock = threading.Lock()
        self._previous_active_window_on_mac = None

        self.shared_state = shared_state
        self.input_loop = input_loop
        self.controller = None  # ControllerInput, attached after the dictionary loads

        self.is_visible = False
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.process_latest_data_loop)
        self.timer.start(10)

        self.probe_label = QLabel()
        self.probe_label.setWordWrap(True)
        self.probe_label.setTextFormat(Qt.TextFormat.RichText)

        self.is_calibrated = False
        self.header_chars_per_line = 50
        self.def_chars_per_line = 50

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.X11BypassWindowManagerHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("background: transparent;")

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        self.frame = QFrame()
        self._apply_frame_stylesheet()
        main_layout.addWidget(self.frame)

        self.content_layout = QVBoxLayout(self.frame)
        self.content_layout.setContentsMargins(10, 10, 10, 10)

        self.display_label = QLabel()
        self.display_label.setWordWrap(True)
        self.display_label.setTextFormat(Qt.TextFormat.RichText)
        self.content_layout.addWidget(self.display_label)

        from meikipop.pronunciation import Pronunciation
        self.pronunciation = Pronunciation(self)
        self.pronunciation.message.connect(lambda text: self.mining_status.setText(text))
        self._pronunciation_key = None
        from meikipop.anki_status import AnkiStatus
        self.anki_status = AnkiStatus(self)
        self.anki_status.updated.connect(self._refresh_anki_status)
        self._mining_word = None
        self.anki_timer = QTimer(self)
        self.anki_timer.timeout.connect(self._check_anki_status)
        self.anki_timer.start(1000)
        self._mining_entries = []
        self._mining_busy = False
        self._mining_grace = 0.0
        self.mining_status = QLabel("Hold Shift · ＋ Anki adds · ▶ replays pronunciation")
        self.mining_status.setWordWrap(True)
        self.mining_status.setStyleSheet("color: #aaaaaa; font-size: 12px;")
        self.content_layout.addWidget(self.mining_status)
        self.display_label.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
        self.display_label.setOpenExternalLinks(False)
        self.display_label.linkActivated.connect(self._mine_clicked)
        self.mining_finished.connect(self._mine_finished)
        self.hide()

    def _apply_frame_stylesheet(self):
        bg_color = QColor(config.color_background)
        r, g, b = bg_color.red(), bg_color.green(), bg_color.blue()
        a = config.background_opacity
        self.probe_label.setFont(QFont(config.font_family))
        self.frame.setStyleSheet(f"""
            QFrame {{
                background-color: rgba({r}, {g}, {b}, {a});
                color: {config.color_foreground};
                border-radius: 8px;
                border: 1px solid #555;
            }}
            QLabel {{
                background-color: transparent;
                border: none;
                font-family: "{config.font_family}";
            }}
            hr {{
                border: none;
                height: 1px;
            }}
        """)

    def _calibrate_empirically(self):
        logger.debug("--- Calibrating Font Metrics Empirically (One-Time) ---")

        # Log font info
        actual_font = self.display_label.font()
        font_info = QFontInfo(actual_font)
        logger.debug(f"[FONT DEBUG] Requested font family: '{config.font_family}' (or default)")
        logger.debug(f"[FONT DEBUG]   -> Actual resolved font family: '{font_info.family()}'")
        logger.debug(f"[FONT DEBUG]   -> Actual style name: '{font_info.styleName()}'")
        logger.debug(f"[FONT DEBUG]   -> Actual point size: {font_info.pointSize()}")
        logger.debug(f"[FONT DEBUG]   -> Actual pixel size: {font_info.pixelSize()}")
        logger.debug(f"[FONT DEBUG]   -> Is it bold? {font_info.bold()}")

        margins = self.content_layout.contentsMargins()
        border_width = 1
        horizontal_padding = margins.left() + margins.right() + (border_width * 2)

        screen = QApplication.primaryScreen()
        self.max_content_width = (int(screen.geometry().width() * 0.4)) - horizontal_padding

        header_font = QFont(config.font_family)
        header_font.setPixelSize(config.font_size_header)
        header_metrics = QFontMetrics(header_font)
        self.header_chars_per_line = self._find_chars_for_width(header_metrics, "Header")

        def_font = QFont(config.font_family)
        def_font.setPixelSize(config.font_size_definitions)
        def_metrics = QFontMetrics(def_font)
        self.def_chars_per_line = self._find_chars_for_width(def_metrics, "Definition")

        logger.debug(f"[CALIBRATE] Max content width: {self.max_content_width}px")
        logger.debug(f"[CALIBRATE] Empirically found {self.header_chars_per_line} header chars/line")
        logger.debug(f"[CALIBRATE] Empirically found {self.def_chars_per_line} definition chars/line")
        self.is_calibrated = True

    def _find_chars_for_width(self, metrics: QFontMetrics, name: str) -> int:
        low = 1
        high = 500
        best_fit = 1

        while low <= high:
            mid = (low + high) // 2
            if mid == 0: break

            test_string = 'x' * mid
            current_width = metrics.horizontalAdvance(test_string)

            if current_width <= self.max_content_width:
                best_fit = mid
                low = mid + 1
            else:
                high = mid - 1

        return best_fit if best_fit > 0 else 50

    def set_latest_data(self, data):
        with self._data_lock:
            self._latest_data = data

    def get_latest_data(self):
        with self._data_lock:
            return self._latest_data

    def process_latest_data_loop(self):
        if not self.is_calibrated:
            self._calibrate_empirically()
        pos = QCursor.pos()
        pad = self.controller is not None and self.controller.navigator.active
        active = (self.input_loop.is_virtual_hotkey_down() or pad) and config.is_enabled
        # Shift release always wins, even while the pointer is inside the popup.
        if not active:
            self.hide_popup()
            if self._pronunciation_key is not None:
                self.pronunciation.stop()
                self._pronunciation_key = None
            return
        # Keep the selected entries fixed while clicking Anki or replaying audio.
        if self.is_visible and (self._mining_busy or (not pad and self.geometry().adjusted(-30, -30, 30, 30).contains(pos))):
            return
        latest = self.get_latest_data()
        if latest and active:
            self._mining_grace = time.monotonic() + 1.2
            needs_check = latest != self._last_latest_data or not self.is_visible
            if latest != self._last_latest_data:
                full_html, new_size = self._calculate_content_and_size_char_count(latest)
                self.display_label.setText(full_html)
                new_size.setHeight(new_size.height() + 48)
                self.setFixedSize(new_size)
                self.mining_status.setText(self._hint(pad))
            changed = latest != self._last_latest_data
            self._mining_entries = latest
            self._last_latest_data = latest
            if pad:
                token = self.controller.navigator.current()
                if token is not None and (changed or not self.is_visible):
                    self._move_below_word(token)
            elif not self.is_visible:
                self.move_to(pos.x(), pos.y())
            self.show_popup()
            if needs_check:
                self._check_anki_status()
            entry = next((e for e in latest if isinstance(e, DictionaryEntry)), None)
            if entry is not None:
                key = (entry.written_form, entry.reading)
                if key != self._pronunciation_key:
                    self._pronunciation_key = key
                    self.pronunciation.play(entry)
        elif not self._mining_busy and time.monotonic() > self._mining_grace:
            self.hide_popup()
            self.pronunciation.stop()
            self._pronunciation_key = None

    @staticmethod
    def _hint(pad):
        if pad:
            return "Ⓐ adds to Anki · Ⓨ replays · Ⓧ next line" if config.vn_mode else "Ⓐ adds to Anki · Ⓧ replays pronunciation"
        return "Hold Shift · ＋ Anki adds · ▶ replays pronunciation"

    def _move_below_word(self, token):
        x, y, w, h = self.controller.token_screen_rect(token)
        screen = QApplication.screenAt(QPoint(int(x), int(y))) or QApplication.primaryScreen()
        geo = screen.geometry()
        gap = 10
        final_y = y + h + gap
        if final_y + self.height() > geo.bottom():
            final_y = y - self.height() - gap
        final_x = max(geo.left(), min(x, geo.right() - self.width()))
        final_y = max(geo.top(), min(final_y, geo.bottom() - self.height()))
        self.move(int(final_x), int(final_y))

    def _first_entry_index(self):
        return next((i for i, e in enumerate(self._mining_entries) if isinstance(e, DictionaryEntry)), None)

    def mine_first_entry(self):
        i = self._first_entry_index()
        if self.is_visible and i is not None:
            self._mine_clicked(f'mine:{i}')

    def replay_first_entry(self):
        i = self._first_entry_index()
        if self.is_visible and i is not None:
            self._mine_clicked(f'audio:{i}')

    def _check_anki_status(self):
        if not self.is_visible or self._mining_busy:
            return
        self.anki_status.request([e.written_form or e.reading for e in self._mining_entries if isinstance(e, DictionaryEntry)])
        self._refresh_anki_status()

    def _refresh_anki_status(self):
        if not self.is_calibrated or not self._mining_entries:
            return
        content, size = self._calculate_content_and_size_char_count(self._mining_entries)
        if content == self.display_label.text():
            return
        self.display_label.setText(content)
        size.setHeight(size.height() + 48)
        self.setFixedSize(size)

    def _mine_clicked(self, link):
        if link.startswith('audio:'):
            try:
                entry = self._mining_entries[int(link.split(':', 1)[1])]
                if isinstance(entry, DictionaryEntry):
                    self.pronunciation.play(entry)
            except (IndexError, ValueError):
                pass
            return
        if self._mining_busy or not link.startswith('mine:'):
            return
        try:
            index = int(link.split(':', 1)[1])
            entry = self._mining_entries[index]
            if not isinstance(entry, DictionaryEntry):
                return
        except (ValueError, IndexError):
            return
        state = self.anki_status.state(entry.written_form or entry.reading)
        if state == 'present':
            self.mining_status.setText("Already in your Anki deck.")
            return
        if state == 'checking':
            self.mining_status.setText("Checking Anki… Please wait.")
            self._check_anki_status()
            return
        frame = getattr(entry, 'mining_window_frame', None)
        if frame is not None and frame.window_id != getattr(self.shared_state, 'capture_window_id', frame.window_id):
            self.mining_status.setText("The selected window has changed. Release Shift and look up the word again.")
            return
        # Freeze audio at click time, before Yomitan/network work can delay it.
        import copy
        entry = copy.copy(entry)
        audio = getattr(self.shared_state, 'game_audio', None)
        try:
            entry.mining_sentence_audio = audio.snapshot(frame.window_id) if audio and frame else None
        except RuntimeError as e:
            self.mining_status.setText(str(e))
            return
        self._mining_word = entry.written_form or entry.reading
        self._mining_busy = True
        self.mining_status.setText("Fetching Yomitan fields and adding to Anki…")
        def work():
            from meikipop.mining import Miner
            try:
                note_id = Miner().add(entry)
                self.mining_finished.emit(True, f"✓ Added to 日本語 · {entry.written_form}")
                logger.info("Anki note created: %s", note_id)
            except Exception as e:
                logger.exception("Anki mining failed")
                self.mining_finished.emit(False, str(e))
        threading.Thread(target=work, name='AnkiMining', daemon=True).start()

    def _mine_finished(self, success, message):
        if success and self._mining_word:
            self.anki_status.mark_added(self._mining_word)
        self._mining_busy = False
        self._mining_grace = time.monotonic() + 6.0
        self.mining_status.setText(message)
        self.mining_status.setStyleSheet("font-size: 12px; color: " + ("#7be3ac" if success else "#ffbd88") + ";")
        self.setMinimumHeight(self.layout().sizeHint().height())

    def _render_kanji_entry(self, entry: KanjiEntry):
        # Colors and sizes from config
        c_word = config.color_highlight_word
        c_read = config.color_highlight_reading
        c_text = config.color_foreground
        fs_head = config.font_size_header
        fs_def = config.font_size_definitions
        show_details = config.show_examples or config.show_components

        readings_str = ", ".join(entry.readings)
        readings_str = f"[{readings_str}]"

        header_html = f"""
                    <span style="font-size:{fs_head}px; color:{c_word}; padding-right: 8px;">{entry.character}</span>
                    <span style="font-size:{fs_head - 2}px; color:{c_read};"> {readings_str}</span>
        """

        meanings_str = ", ".join(entry.meanings)
        meanings_html = f'<span style="font-size:{fs_def}px; color:{c_text};"> {meanings_str}</span>'
        if not config.compact_mode:
            meanings_html = f'<span style="font-size:{fs_def}px; color:{c_text};"> [字]</span><div>{meanings_html}</div>'

        examples_html = ""
        if config.show_examples:
            ex_parts = []
            for ex in entry.examples:
                part = (f"<span style='font-size:{fs_head - 2}px; color:{c_word}'>{ex['w']}</span> "
                        f"<span style='font-size:{fs_def}px; color:{c_read}'>[{ex['r']}]</span> "
                        f"<span style='font-size:{fs_def}px; color:{c_text}'>{ex['m']}</span>")
                ex_parts.append(part)
            if ex_parts:
                examples_html = f'<div>' \
                                f'{"; ".join(ex_parts)}</div>'

        components_html = ""
        if config.show_components:
            comp_parts = []
            for c in entry.components:
                part = (f"<span style='font-size:{fs_def}px; color:{c_word}'>{c.get('c', '')}</span> "
                        f"<span style='font-size:{fs_def}px; color:{c_text}'>{c.get('m', '')}</span>")
                comp_parts.append(part)
            if comp_parts:
                components_html = f'<div>{", ".join(comp_parts)}</div>'

        return f"""
        <div style="border: 1px solid {config.color_highlight_word};">
            {header_html}
            {meanings_html}
            {examples_html}
            {components_html}
        </div>
        """

    def _calculate_content_and_size_char_count(self, entries: Optional[List[DictionaryEntry]]) -> tuple[
        Optional[str], Optional[QSize]]:
        if not self.is_calibrated: return None, None
        if not entries: return None, None

        all_html_parts = []
        max_ratio = 0.0

        for i, entry in enumerate(entries):
            if i > 0:
                all_html_parts.append('<hr style="margin-top: 0px; margin-bottom: 0px;">')

            if isinstance(entry, KanjiEntry):
                header_definition = ', '.join(
                    entry.meanings) if config.show_examples or config.show_components else '[字]'
                header_text_calc = f"{entry.character} {', '.join(entry.readings)} {header_definition}"
                max_ratio = max(max_ratio, len(header_text_calc) / self.header_chars_per_line)

                max_ratio = max(max_ratio, 0.7)

                all_html_parts.append(self._render_kanji_entry(entry))
                continue

            header_text_calc = entry.written_form + " ✓ Already in Anki ▶"
            if entry.reading: header_text_calc += f" [{entry.reading}]"
            header_ratio = len(header_text_calc) / self.header_chars_per_line
            max_ratio = max(max_ratio, header_ratio)

            # --- HTML construction ---
            state = self.anki_status.state(entry.written_form or entry.reading)
            badge = {'present': '✓ Already in Anki', 'checking': 'Checking Anki…',
                     'unknown': 'Anki unavailable · retry', 'absent': '＋ Anki'}[state]
            word = html.escape(entry.written_form)
            if state in ('present', 'checking'):
                header_html = f'<span style="color:{config.color_highlight_word};font-size:{config.font_size_header}px;">{word}</span> <span style="color:#aaaaaa;font-size:14px;">{badge}</span>'
            else:
                header_html = f'<a href="mine:{i}" style="color:{config.color_highlight_word};font-size:{config.font_size_header}px;">{word}</a> <a href="mine:{i}" style="color:{config.color_highlight_reading};font-size:14px;">{badge}</a>'
            header_html += f' <a href="audio:{i}" style="color:{config.color_highlight_reading};font-size:14px;">▶</a>'
            if entry.reading: header_html += f' <span style="color: {config.color_highlight_reading}; font-size:{config.font_size_header - 2}px;">[{entry.reading}]</span>'
            if entry.deconjugation_process and config.show_deconjugation:
                deconj_str = " ← ".join(p for p in entry.deconjugation_process if p)
                if deconj_str:
                    header_html += f' <span style="color:{config.color_foreground}; font-size:{config.font_size_definitions - 2}px; opacity:0.8;">({deconj_str})</span>'
            if config.show_frequency and entry.freq < 999_999:
                header_html += f' <span style="color:{config.color_foreground}; font-size:{config.font_size_definitions - 2}px; opacity:0.6;">#{entry.freq}</span>'
            def_text_parts_calc = []
            def_text_parts_html = []
            last_dict = None
            for idx, sense in enumerate(entry.senses):
                glosses = sense.get('glosses', [])
                glosses_str = ""
                if glosses:
                    glosses_str = ", ".join(glosses) if config.show_all_glosses else sense.get('glosses')[0]
                if sense.get('dict') and len(glosses_str) > USER_GLOSS_LIMIT:
                    glosses_str = glosses_str[:USER_GLOSS_LIMIT].rstrip() + "…"
                glosses_str = html.escape(glosses_str)
                pos_list  = sense.get('pos', [])
                tags_list = sense.get('tags', [])
                sense_calc = f"({idx + 1})" if config.show_all_glosses else ""
                sense_html = f"<b>({idx + 1})</b> " if config.show_all_glosses else ""
                source = sense.get('dict')
                if source and source != last_dict:
                    sense_calc = f"[{source}] " + sense_calc
                    sense_html = f'<span style="color:{config.color_highlight_reading}; font-size:{config.font_size_definitions - 2}px;">[{html.escape(source)}]</span> ' + sense_html
                last_dict = source
                if config.show_pos and pos_list:
                    pos_str = f' ({", ".join(pos_list)})'
                    sense_calc += pos_str
                    sense_html += f'<span style="color:{config.color_foreground}; opacity:0.7;"><i>{pos_str}</i></span> '
                if config.show_tags and tags_list:
                    tags_str = f' [{", ".join(tags_list)}]'
                    sense_calc += tags_str
                    sense_html += f'<span style="color:{config.color_foreground}; font-size:{config.font_size_definitions - 2}px; opacity:0.7;">{tags_str}</span> '
                sense_calc += glosses_str
                sense_html += glosses_str
                def_text_parts_calc.append(sense_calc)
                def_text_parts_html.append(sense_html)

            if config.compact_mode:
                separator = "; "
                full_def_text_html = separator.join(def_text_parts_html)
                def_ratio = len(separator.join(def_text_parts_calc)) / self.def_chars_per_line
                max_ratio = max(max_ratio, def_ratio)
            else:
                separator = "<br>"
                full_def_text_html = separator.join(def_text_parts_html)
                for def_text_calc in def_text_parts_calc:
                    def_ratio = len(def_text_calc) / self.def_chars_per_line
                    max_ratio = max(max_ratio, def_ratio)

            definitions_html_final = f'{" " if config.compact_mode else "<br>"}<span style="font-size:{config.font_size_definitions}px;">{full_def_text_html}</span>'
            all_html_parts.append(f"{header_html}{definitions_html_final}")

        optimal_content_width = self.max_content_width * min(1.0, max_ratio)
        optimal_content_width = max(optimal_content_width, 200)

        full_html = "".join(all_html_parts)
        self.probe_label.setText(full_html)

        final_height = self.probe_label.heightForWidth(int(optimal_content_width))

        margins = self.content_layout.contentsMargins()
        border_width = 1
        horizontal_padding = margins.left() + margins.right() + (border_width * 2)
        vertical_padding = margins.top() + margins.bottom() + (border_width * 2)

        final_size = QSize(int(optimal_content_width) + horizontal_padding, final_height + vertical_padding)
        return full_html, final_size

    def move_to(self, x, y):
        cursor_point = QPoint(x, y)
        screen = QApplication.screenAt(cursor_point) or QApplication.primaryScreen()
        screen_geo = screen.geometry()
        popup_size = self.size()
        offset = 15

        ratio = screen.devicePixelRatio()
        x, y = magpie_manager.transform_raw_to_visual((int(x), int(y)), ratio)

        # --- Positioning logic based on mode ---
        mode = config.popup_position_mode

        if mode == 'visual_novel_mode':
            # --- Vertical Position (VN Mode) ---
            screen_height = screen_geo.height()
            cursor_y_in_screen = y - screen_geo.top()
            is_below = True
            if cursor_y_in_screen > (2 * screen_height / 3):  # Lower third
                is_below = False  # Place above
            elif cursor_y_in_screen < (screen_height / 3):  # Upper third
                is_below = True  # Place below
            else:  # Middle third
                is_below = cursor_y_in_screen < (screen_height / 2)
            final_y = (y + offset) if is_below else (y - popup_size.height() - offset)

            # Vertical Push
            if final_y < screen_geo.top(): final_y = screen_geo.top()
            if final_y + popup_size.height() > screen_geo.bottom():
                final_y = screen_geo.bottom() - popup_size.height()

            # --- Horizontal Position (VN Mode) ---
            screen_width = screen_geo.width()
            cursor_x_in_screen = x - screen_geo.left()
            # Define anchor points for interpolation
            pos_right = x + offset
            pos_center = x - popup_size.width() / 2.0
            pos_left = x - popup_size.width() - offset

            # Interpolate smoothly between right, center, and left alignment
            if cursor_x_in_screen < screen_width / 2.0:
                ratio = cursor_x_in_screen / (screen_width / 2.0)
                final_x = pos_right * (1 - ratio) + pos_center * ratio
            else:
                ratio = (cursor_x_in_screen - (screen_width / 2.0)) / (screen_width / 2.0)
                final_x = pos_center * (1 - ratio) + pos_left * ratio

        elif mode == 'flip_horizontally':
            # X: Flip, Y: Push
            preferred_x = x + offset
            final_x = preferred_x if preferred_x + popup_size.width() <= screen_geo.right() else x - popup_size.width() - offset

            final_y = y + offset
            if final_y + popup_size.height() > screen_geo.bottom(): final_y = screen_geo.bottom() - popup_size.height()
            if final_y < screen_geo.top(): final_y = screen_geo.top()

        elif mode == 'flip_vertically':
            # X: Push, Y: Flip
            final_x = x + offset
            if final_x + popup_size.width() > screen_geo.right(): final_x = screen_geo.right() - popup_size.width()
            if final_x < screen_geo.left(): final_x = screen_geo.left()

            preferred_y = y + offset
            final_y = preferred_y if preferred_y + popup_size.height() <= screen_geo.bottom() else y - popup_size.height() - offset

        else:  # 'flip_both'
            # X: Flip
            preferred_x = x + offset
            final_x = preferred_x if preferred_x + popup_size.width() <= screen_geo.right() else x - popup_size.width() - offset

            # Y: Flip
            preferred_y = y + offset
            final_y = preferred_y if preferred_y + popup_size.height() <= screen_geo.bottom() else y - popup_size.height() - offset

        # Final clamp to ensure the popup is always fully visible.
        # This acts as a safeguard against any edge cases.
        final_x = max(screen_geo.left(), min(final_x, screen_geo.right() - popup_size.width()))
        final_y = max(screen_geo.top(), min(final_y, screen_geo.bottom() - popup_size.height()))

        self.move(int(final_x), int(final_y))

    def hide_popup(self):
        # logger.debug(f"hide_popup triggered while visibility:{self.is_visible}")
        if not self.is_visible:
            return
        self.hide()
        self.is_visible = False
        QTimer.singleShot(50, lambda: self._release_lock_safely())  # prevent popup from being screenshotted
        self._restore_focus_on_mac()

    def _release_lock_safely(self):
        logger.debug("hide_popup releasing lock...")
        self.shared_state.screen_lock.release()
        logger.debug("...successfully released lock by hide_popup")

    def show_popup(self):
        # logger.debug(f"show_popup triggered while visibility:{self.is_visible}")
        if self.is_visible:
            return
        logger.debug("show_popup acquiring lock...")
        self.shared_state.screen_lock.acquire()
        logger.debug("...successfully acquired lock by show_popup")

        self._store_active_window_on_mac()
        self.show()
        from meikipop.gui.overlay import float_over_fullscreen
        float_over_fullscreen(self)  # Qt resets the level on every show
        if IS_MACOS:
            self.raise_()

        self.is_visible = True

    def reapply_settings(self):
        logger.debug("Popup: Re-applying settings and triggering font recalibration.")
        self._apply_frame_stylesheet()
        # By setting is_calibrated to False, the main loop will automatically
        # run _calibrate_empirically() again with the new font settings.
        self.is_calibrated = False

    def _store_active_window_on_mac(self):
        """Store the currently active window for focus restoration (macOS only)."""
        if not IS_MACOS or not Quartz:
            return

        try:
            # Get the currently active application
            active_app = Quartz.NSWorkspace.sharedWorkspace().frontmostApplication()
            from AppKit import NSRunningApplication
            if active_app and active_app.processIdentifier() == NSRunningApplication.currentApplication().processIdentifier():
                active_app = None  # controller mode activated us; it hands focus back itself
            if active_app:
                # Store the application reference instead of trying to get the window
                # We'll use the application to restore focus later
                self._previous_active_window_on_mac = active_app
        except Exception as e:
            logger.warning(f"Failed to store active window: {e}")
            self._previous_active_window_on_mac = None

    def _restore_focus_on_mac(self):
        """Restore focus to the previously active application (macOS only)."""
        if not IS_MACOS or not Quartz or not self._previous_active_window_on_mac:
            return

        try:
            # Activate the previously active application
            self._previous_active_window_on_mac.activateWithOptions_(Quartz.NSApplicationActivateAllWindows)
        except Exception as e:
            logger.warning(f"Failed to restore focus: {e}")
        finally:
            # Clear the stored application reference
            self._previous_active_window_on_mac = None
