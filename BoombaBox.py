import sys
import os
import vlc
from mutagen import File
from mutagen.id3 import ID3, APIC
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QListWidget, QPushButton, QLabel, QLineEdit,
    QTabWidget, QSplitter, QSlider, QStyle,
    QScrollArea, QGridLayout, QFrame
)
from PyQt5.QtCore import Qt, QTimer, QSize
from PyQt5.QtGui import QPixmap, QImage
import io


MUSIC_DIR = "music"  # folder with songs


def scan_music_folder(folder):
    songs = []
    for root, _, files in os.walk(folder):
        for f in files:
            if f.lower().endswith((".mp3", ".wav", ".flac", ".ogg")):
                path = os.path.join(root, f)
                meta = File(path, easy=True)
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

        self.songs = scan_music_folder(MUSIC_DIR)
        self.filtered_songs = self.songs.copy()
        self.current_index = -1

        self.init_ui()

        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.update_progress)

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

        self.populate_song_grid()

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
            frame.mouseDoubleClickEvent = lambda e, index=idx: self.play_song(index)

            self.grid_layout.addWidget(frame, row, col)
            col += 1
            if col >= columns:
                col = 0
                row += 1

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
