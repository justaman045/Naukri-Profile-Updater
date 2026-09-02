from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QSizePolicy


class WrappingValueLabel(QLabel):
    """A word-wrapping QLabel that reports its true wrapped height.

    Qt's plain ``QLabel`` under-reports ``heightForWidth`` for wrapped text in
    some layouts (``QFormLayout`` rows, labels inside a ``QScrollArea``), so rows
    come out too short and the wrapped text is vertically clipped (first line cut
    from the top, last line hidden). This subclass computes the real wrapped
    height from the font metrics so the layout allocates enough room.
    """

    def heightForWidth(self, width: int) -> int:
        if not self.text() or width <= 0:
            return super().heightForWidth(width)
        box = self.fontMetrics().boundingRect(
            0, 0, width, 100_000,
            int(Qt.TextFlag.TextWordWrap),
            self.text(),
        )
        return int(box.height()) + 4


def make_wrapping_status_label(text: str = "") -> QLabel:
    """A word-wrapping status QLabel that cannot force the window wider.

    Uses an ``Ignored`` horizontal size policy so long, unbreakable text wraps
    within the window's current width instead of enlarging the window.
    """
    label = _config_label(WrappingValueLabel(text), QSizePolicy.Policy.Ignored)
    return label


def make_wrapping_form_label(text: str = "") -> QLabel:
    """A word-wrapping QLabel for a ``QFormLayout`` value row.

    Uses a ``Preferred`` horizontal size policy (with the true wrapped height
    from :class:`WrappingValueLabel`) so the form sizes the row to the full
    wrapped text instead of clipping it.
    """
    label = _config_label(WrappingValueLabel(text), QSizePolicy.Policy.Preferred)
    return label


def _config_label(label: QLabel, horizontal: QSizePolicy.Policy) -> QLabel:
    label.setWordWrap(True)
    label.setSizePolicy(QSizePolicy(horizontal, QSizePolicy.Policy.Preferred))
    return label