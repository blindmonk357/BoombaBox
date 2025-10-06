import sys
import os
import json
import vlc
from mutagen import File
from mutagen.id3 import ID3, APIC
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QListWidget, QPushButton, QLabel, QLineEdit,
    QTabWidget, QSplitter, QSlider, QStyle,
    QScrollArea, QGridLayout, QFrame, QMenu,
    QAction, QInputDialog, QMessageBox
)
from PyQt5.QtCore import Qt, QTimer, QSize, QPoint
from PyQt5.QtGui import QPixmap, QImage
import io
from functools import partial


MUSIC_DIR = "music"  # folder with songs
PLAYLIST_FILE = "playlists.json"  # persisted in same folder as script


def scan_music_folder(folder):
    songs = []
    for root, _, files in os.walk(folder):
        for f in files:
            if f.lower().endswith((".mp3", ".wav", ".flac", ".ogg")):
                path = os.path.join(root, f)
                try:
                    meta = File(path, easy=True) or {}
                except:
                    meta = {}
                album_art = None

                if f.lower().endswith(".mp3"):
                    try:
                        tags = ID3(path)
                        for tag in tags.values():
                            if isinstance(tag, APIC):
                                album_art = QImage.fromData(tag.data)
                                break
                    except:
                        pass

                songs.append({
                    "title": meta.get("title", [os.path.splitext(f)[0]])[0],
                    "artist": meta.get("artist", ["Unknown Artist"])[0],
                    "album": meta.get("album", ["Unknown Album"])[0],
                    "genre": meta.get("genre", ["Unknown Genre"])[0],
                    "file": path,
                    "art": album_art
                })
    return songs


class ClickableSlider(QSlider):
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            val = QStyle.sliderValueFromPosition(
                self.minimum(), self.maximum(),
                event.x(), self.width()
            )
            self.setValue(val)
            self.sliderReleased.emit()
        super().mousePressEvent(event)


class MusicPlayer(QWidget):
    TILE_WIDTH = 180
    TILE_HEIGHT = 220

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Boomba FM - Music Player")
        self.setGeometry(200, 200, 900, 600)

        self.vlc_instance = vlc.Instance()
        self.player = self.vlc_instance.media_player_new()

        # Scan music first so we can attach art when loading playlists
        self.songs = scan_music_folder(MUSIC_DIR)
        self.filtered_songs = self.songs.copy()
        self.current_index = -1

        # playlists stored in memory: { name: [song_dicts...] }
        # load from JSON (if exists)
        self.playlists = self.load_playlists()
        self.current_playlist_name = None

        self.init_ui()

        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.update_progress)

    # ------------------ Persistence helpers ------------------
    def load_playlists(self):
        """
        Load playlists from PLAYLIST_FILE.
        Stored format: { "name": [ {title,artist,album,genre,file}, ... ], ... }
        When loading, try to match each saved song by file path with scanned songs to reattach 'art'.
        """
        if not os.path.exists(PLAYLIST_FILE):
            return {}
        try:
            with open(PLAYLIST_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception as e:
            print("Error reading playlists file:", e)
            return {}

        # Build a map of current songs by file path for art/metadata attachment
        path_map = {s["file"]: s for s in self.songs}

        playlists = {}
        for pname, items in raw.items():
            playlists[pname] = []
            if not isinstance(items, list):
                continue
            for it in items:
                # expected keys: title, artist, album, genre, file
                file_path = it.get("file")
                if file_path in path_map:
                    # use the scanned song dict (has QImage art)
                    playlists[pname].append(path_map[file_path])
                else:
                    # file missing from current scan — recreate minimal dict without art
                    playlists[pname].append({
                        "title": it.get("title", os.path.splitext(os.path.basename(file_path or ""))[0]),
                        "artist": it.get("artist", "Unknown Artist"),
                        "album": it.get("album", "Unknown Album"),
                        "genre": it.get("genre", "Unknown Genre"),
                        "file": file_path or "",
                        "art": None
                    })
        return playlists

    def save_playlists(self):
        """
        Save playlists to PLAYLIST_FILE. Strip non-serializable fields (like QImage) before writing.
        """
        serial = {}
        for pname, items in self.playlists.items():
            serial[pname] = []
            for s in items:
                serial[pname].append({
                    "title": s.get("title", ""),
                    "artist": s.get("artist", ""),
                    "album": s.get("album", ""),
                    "genre": s.get("genre", ""),
                    "file": s.get("file", "")
                })
        try:
            with open(PLAYLIST_FILE, "w", encoding="utf-8") as f:
                json.dump(serial, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print("Error saving playlists:", e)

    # ---------------------------------------------------------

    def init_ui(self):
        layout = QVBoxLayout()

        self.tabs = QTabWidget()

        # --- Library tab with grid view ---
        self.library_tab = QWidget()
        lib_layout = QVBoxLayout()

        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Search by artist, album, genre...")
        self.search_bar.textChanged.connect(self.apply_filter)
        lib_layout.addWidget(self.search_bar)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.grid_widget = QWidget()
        self.grid_layout = QGridLayout()
        self.grid_layout.setSpacing(20)
        self.grid_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.grid_widget.setLayout(self.grid_layout)
        self.scroll_area.setWidget(self.grid_widget)
        lib_layout.addWidget(self.scroll_area)

        self.library_tab.setLayout(lib_layout)
        self.tabs.addTab(self.library_tab, "Library")

        # --- Browse tab ---
        self.browse_tab = QWidget()
        browse_layout = QHBoxLayout()

        self.artist_list = QListWidget()
        self.album_list = QListWidget()
        self.genre_list = QListWidget()

        self.artist_list.itemClicked.connect(lambda: self.filter_by("artist"))
        self.album_list.itemClicked.connect(lambda: self.filter_by("album"))
        self.genre_list.itemClicked.connect(lambda: self.filter_by("genre"))

        splitter = QSplitter()
        splitter.addWidget(self.artist_list)
        splitter.addWidget(self.album_list)
        splitter.addWidget(self.genre_list)
        browse_layout.addWidget(splitter)

        self.populate_browse_lists()

        self.browse_tab.setLayout(browse_layout)
        self.tabs.addTab(self.browse_tab, "Browse")

        # --- Playlists tab ---
        self.init_playlists_tab()

        layout.addWidget(self.tabs)

        # --- Controls ---
        controls = QHBoxLayout()

        self.prev_button = QPushButton("⏮ Prev")
        self.prev_button.clicked.connect(self.prev_song)
        controls.addWidget(self.prev_button)

        self.play_button = QPushButton("▶ Play")
        self.play_button.clicked.connect(self.toggle_play_pause)
        controls.addWidget(self.play_button)

        self.next_button = QPushButton("⏭ Next")
        self.next_button.clicked.connect(self.next_song)
        controls.addWidget(self.next_button)

        # --- Volume slider ---
        self.volume_label = QLabel("🔊")
        controls.addWidget(self.volume_label)

        self.volume_slider = ClickableSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(70)
        self.volume_slider.setFixedWidth(150)
        self.volume_slider.sliderReleased.connect(self.set_volume)
        self.volume_slider.valueChanged.connect(self.set_volume)
        controls.addWidget(self.volume_slider)

        layout.addLayout(controls)

        # --- Progress bar ---
        self.progress = ClickableSlider(Qt.Horizontal)
        self.progress.setRange(0, 1000)
        self.progress.sliderReleased.connect(self.seek_song)
        layout.addWidget(self.progress)

        self.time_label = QLabel("00:00 / 00:00")
        layout.addWidget(self.time_label)

        # Now playing label
        self.now_playing = QLabel("No song playing")
        layout.addWidget(self.now_playing)

        self.setLayout(layout)

        # populate UI
        self.populate_song_grid()
        # populate playlist names from loaded playlists
        self.populate_playlist_name_list()

    # --- Playlists UI and logic ---
    def init_playlists_tab(self):
        self.playlists_tab = QWidget()
        tab_layout = QHBoxLayout()

        # Left: list of playlist names + controls
        left = QVBoxLayout()
        self.playlist_name_list = QListWidget()
        self.playlist_name_list.itemClicked.connect(self.select_playlist)
        left.addWidget(self.playlist_name_list)

        name_controls = QHBoxLayout()
        self.new_playlist_btn = QPushButton("＋ New")
        self.new_playlist_btn.clicked.connect(self.create_playlist)
        name_controls.addWidget(self.new_playlist_btn)

        self.delete_playlist_btn = QPushButton("🗑 Delete")
        self.delete_playlist_btn.clicked.connect(self.delete_playlist)
        name_controls.addWidget(self.delete_playlist_btn)

        left.addLayout(name_controls)
        tab_layout.addLayout(left, 1)

        # Right: songs in selected playlist
        right = QVBoxLayout()
        self.playlist_song_list = QListWidget()
        self.playlist_song_list.itemDoubleClicked.connect(self.play_from_playlist)
        # context menu for removing
        self.playlist_song_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.playlist_song_list.customContextMenuRequested.connect(self.show_playlist_context_menu)
        right.addWidget(self.playlist_song_list)
        tab_layout.addLayout(right, 3)

        self.playlists_tab.setLayout(tab_layout)
        self.tabs.addTab(self.playlists_tab, "Playlists")

    def populate_playlist_name_list(self):
        # populate left-hand playlist name list from self.playlists
        self.playlist_name_list.clear()
        for name in sorted(self.playlists.keys()):
            self.playlist_name_list.addItem(name)

    def create_playlist(self):
        name, ok = QInputDialog.getText(self, "Create Playlist", "Playlist name:")
        if ok and name:
            if name in self.playlists:
                QMessageBox.warning(self, "Exists", "A playlist with that name already exists.")
                return
            self.playlists[name] = []
            self.playlist_name_list.addItem(name)
            self.save_playlists()

    def delete_playlist(self):
        row = self.playlist_name_list.currentRow()
        if row < 0:
            return
        name = self.playlist_name_list.currentItem().text()
        confirm = QMessageBox.question(self, "Delete Playlist", f"Delete playlist '{name}'?", QMessageBox.Yes | QMessageBox.No)
        if confirm == QMessageBox.Yes:
            self.playlists.pop(name, None)
            self.playlist_name_list.takeItem(row)
            # clear right pane if it was the current
            if self.current_playlist_name == name:
                self.current_playlist_name = None
                self.playlist_song_list.clear()
            self.save_playlists()

    def select_playlist(self, item):
        if not item:
            return
        name = item.text()
        self.current_playlist_name = name
        self.refresh_playlist_song_list()

    def refresh_playlist_song_list(self):
        self.playlist_song_list.clear()
        if not self.current_playlist_name:
            return
        songs = self.playlists.get(self.current_playlist_name, [])
        for s in songs:
            self.playlist_song_list.addItem(f"{s.get('title','?')} - {s.get('artist','?')}")

    def play_from_playlist(self, item):
        index = self.playlist_song_list.row(item)
        if index < 0:
            return
        songs = self.playlists.get(self.current_playlist_name, [])
        if index >= len(songs):
            return
        song = songs[index]
        media = self.vlc_instance.media_new(song["file"])
        self.player.set_media(media)
        self.player.play()
        self.player.audio_set_volume(self.volume_slider.value())
        self.play_button.setText("⏸ Pause")
        self.now_playing.setText(f"Now Playing: {song.get('title','?')} - {song.get('artist','?')}")
        self.timer.start()

    def show_playlist_context_menu(self, pos: QPoint):
        item = self.playlist_song_list.itemAt(pos)
        if not item:
            return
        menu = QMenu()
        remove_action = QAction("Remove from Playlist", self)
        remove_action.triggered.connect(partial(self.remove_song_from_current_playlist, self.playlist_song_list.row(item)))
        menu.addAction(remove_action)
        menu.exec_(self.playlist_song_list.viewport().mapToGlobal(pos))

    def remove_song_from_current_playlist(self, index):
        if not self.current_playlist_name:
            return
        songs = self.playlists.get(self.current_playlist_name, [])
        if 0 <= index < len(songs):
            songs.pop(index)
            self.refresh_playlist_song_list()
            self.save_playlists()

    # --- Library grid (with right-click Add to Playlist) ---
    def populate_song_grid(self):
        # Clear previous
        for i in reversed(range(self.grid_layout.count())):
            widget = self.grid_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)

        columns = 4
        row = 0
        col = 0

        for idx, song in enumerate(self.filtered_songs):
            frame = QFrame()
            frame.setFrameShape(QFrame.StyledPanel)
            frame.setFixedSize(self.TILE_WIDTH, self.TILE_HEIGHT)
            v_layout = QVBoxLayout()
            v_layout.setContentsMargins(0, 0, 0, 0)

            # Album art
            if song["art"]:
                pixmap = QPixmap.fromImage(song["art"])
            else:
                pixmap = QPixmap(self.TILE_WIDTH, 140)
                pixmap.fill(Qt.gray)
            label_art = QLabel()
            label_art.setPixmap(pixmap.scaled(self.TILE_WIDTH, 140, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            label_art.setAlignment(Qt.AlignCenter)
            v_layout.addWidget(label_art)

            # Title
            label_title = QLabel(song["title"])
            label_title.setAlignment(Qt.AlignLeft)
            v_layout.addWidget(label_title)

            # Artist
            label_artist = QLabel(song["artist"])
            label_artist.setAlignment(Qt.AlignLeft)
            v_layout.addWidget(label_artist)

            v_layout.addStretch()
            frame.setLayout(v_layout)

            # double click to play
            frame.mouseDoubleClickEvent = partial(self._frame_double_click_play, idx)

            # right-click context menu to add to playlist
            frame.setContextMenuPolicy(Qt.CustomContextMenu)
            frame.customContextMenuRequested.connect(partial(self.show_library_context_menu, idx))

            self.grid_layout.addWidget(frame, row, col)
            col += 1
            if col >= columns:
                col = 0
                row += 1

    def _frame_double_click_play(self, index, event):
        # keep signature similar to original mouseDoubleClickEvent
        self.play_song(index)

    def show_library_context_menu(self, idx, pos):
        # idx is index into self.filtered_songs
        menu = QMenu()
        add_menu = QMenu("Add to Playlist", self)
        if not self.playlists:
            no_action = QAction("No playlists (create one first)", self)
            no_action.setEnabled(False)
            add_menu.addAction(no_action)
        else:
            for name in sorted(self.playlists.keys()):
                action = QAction(name, self)
                action.triggered.connect(partial(self.add_song_to_playlist_by_name, idx, name))
                add_menu.addAction(action)
        menu.addMenu(add_menu)
        # Option to create new playlist directly
        create_action = QAction("Create new playlist...", self)
        create_action.triggered.connect(partial(self.create_playlist_from_song, idx))
        menu.addAction(create_action)

        # show menu at global pos relative to the widget that sent the signal
        sender = self.sender()
        if hasattr(sender, "mapToGlobal"):
            global_pos = sender.mapToGlobal(pos)
        else:
            global_pos = QPoint(pos)
        menu.exec_(global_pos)

    def add_song_to_playlist_by_name(self, idx, playlist_name):
        if playlist_name not in self.playlists:
            return
        song = self.filtered_songs[idx]
        playlist = self.playlists[playlist_name]
        # avoid duplicates by file path
        if any(s.get("file") == song.get("file") for s in playlist):
            QMessageBox.information(self, "Already added", f"'{song['title']}' is already in '{playlist_name}'.")
            return
        # store the song dict (it contains 'art' which isn't JSON-serializable, but save_playlists strips it)
        playlist.append(song)
        if self.current_playlist_name == playlist_name:
            self.refresh_playlist_song_list()
        self.save_playlists()

    def create_playlist_from_song(self, idx):
        name, ok = QInputDialog.getText(self, "Create Playlist", "Playlist name:")
        if ok and name:
            if name in self.playlists:
                QMessageBox.warning(self, "Exists", "A playlist with that name already exists.")
                return
            self.playlists[name] = []
            self.playlist_name_list.addItem(name)
            # add this song immediately
            self.add_song_to_playlist_by_name(idx, name)
            self.save_playlists()

    # --- Browse lists and filters remain unchanged ---
    def populate_browse_lists(self):
        self.artist_list.clear()
        self.album_list.clear()
        self.genre_list.clear()
        artists = sorted(set(s["artist"] for s in self.songs))
        albums = sorted(set(s["album"] for s in self.songs))
        genres = sorted(set(s["genre"] for s in self.songs))
        self.artist_list.addItems(artists)
        self.album_list.addItems(albums)
        self.genre_list.addItems(genres)

    def apply_filter(self, text):
        text = text.lower()
        self.filtered_songs = [
            s for s in self.songs
            if text in s["artist"].lower()
            or text in s["album"].lower()
            or text in s["genre"].lower()
            or text in s["title"].lower()
        ]
        self.populate_song_grid()

    def filter_by(self, field):
        item = self.sender().currentItem()
        if not item:
            return
        value = item.text()
        self.filtered_songs = [s for s in self.songs if s[field] == value]
        self.populate_song_grid()
        self.tabs.setCurrentWidget(self.library_tab)

    def play_song(self, row=None):
        if row is None:
            return
        if row < 0 or row >= len(self.filtered_songs):
            return

        self.current_index = row
        song = self.filtered_songs[row]

        media = self.vlc_instance.media_new(song["file"])
        self.player.set_media(media)
        self.player.play()
        self.player.audio_set_volume(self.volume_slider.value())

        self.play_button.setText("⏸ Pause")
        self.now_playing.setText(f"Now Playing: {song['title']} - {song['artist']}")
        self.timer.start()

    def toggle_play_pause(self):
        if self.player.is_playing():
            self.player.pause()
            self.play_button.setText("▶ Play")
        else:
            if self.current_index == -1 and self.filtered_songs:
                self.play_song(0)
            else:
                self.player.play()
                self.play_button.setText("⏸ Pause")

    def next_song(self):
        if self.current_index < len(self.filtered_songs) - 1:
            self.current_index += 1
            self.play_song(self.current_index)

    def prev_song(self):
        if self.current_index > 0:
            self.current_index -= 1
            self.play_song(self.current_index)

    def update_progress(self):
        if not self.player:
            return
        length = self.player.get_length()
        pos = self.player.get_time()

        if length > 0:
            self.progress.blockSignals(True)
            self.progress.setValue(int(pos / length * 1000))
            self.progress.blockSignals(False)

            elapsed = self.format_time(pos // 1000)
            total = self.format_time(length // 1000)
            self.time_label.setText(f"{elapsed} / {total}")

    def seek_song(self):
        if not self.player:
            return
        length = self.player.get_length()
        if length > 0:
            val = self.progress.value() / 1000
            self.player.set_time(int(val * length))

    def set_volume(self):
        vol = self.volume_slider.value()
        self.player.audio_set_volume(vol)

    @staticmethod
    def format_time(seconds):
        m, s = divmod(int(seconds), 60)
        return f"{m:02}:{s:02}"


if __name__ == "__main__":
    app = QApplication(sys.argv)
    player = MusicPlayer()
    player.show()
    sys.exit(app.exec_())
