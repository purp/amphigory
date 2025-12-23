"""Custom dialogs using AppKit for Amphigory daemon."""

import logging
import webbrowser
from dataclasses import dataclass
from typing import Optional

# PyObjC imports
try:
    from AppKit import (
        NSAlert,
        NSAlertFirstButtonReturn,
        NSApp,
        NSApplication,
        NSButton,
        NSFont,
        NSImage,
        NSImageNameInfo,
        NSMakeRect,
        NSTextField,
        NSTextFieldCell,
        NSView,
        NSModalResponseOK,
        NSRunningApplication,
        NSApplicationActivateIgnoringOtherApps,
    )
    from Foundation import NSObject
    HAS_APPKIT = True
except ImportError:
    HAS_APPKIT = False

logger = logging.getLogger(__name__)


@dataclass
class DialogResult:
    """Result from a dialog."""
    cancelled: bool = True
    url: Optional[str] = None
    directory: Optional[str] = None


class ConfigDialog:
    """
    Configuration dialog with two labeled input fields.

    Uses AppKit for native macOS look and feel.
    """

    def __init__(
        self,
        initial_url: str = "",
        initial_directory: str = "",
        wiki_url: str = "",
    ):
        """
        Initialize the configuration dialog.

        Args:
            initial_url: Pre-filled value for URL field
            initial_directory: Pre-filled value for directory field
            wiki_url: URL to wiki documentation
        """
        self.initial_url = initial_url
        self.initial_directory = initial_directory
        self.wiki_url = wiki_url

        # These will be set when dialog is built
        self.url_field: Optional[NSTextField] = None
        self.directory_field: Optional[NSTextField] = None

    def run(self) -> DialogResult:
        """
        Show the dialog and return the result.

        Returns:
            DialogResult with user's input or cancelled=True
        """
        if not HAS_APPKIT:
            logger.warning("AppKit not available - cannot show dialog")
            return DialogResult(cancelled=True)

        # Bring app to front
        app = NSRunningApplication.currentApplication()
        app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)

        # Create alert
        alert = NSAlert.alloc().init()
        alert.setMessageText_("Connect to Amphigory")
        alert.setInformativeText_("")
        alert.addButtonWithTitle_("Save")
        alert.addButtonWithTitle_("Cancel")

        # Create accessory view with fields
        accessory = self._create_accessory_view()
        alert.setAccessoryView_(accessory)

        # Show dialog
        alert.window().setInitialFirstResponder_(self.url_field)
        response = alert.runModal()

        if response == NSAlertFirstButtonReturn:
            return DialogResult(
                cancelled=False,
                url=str(self.url_field.stringValue()),
                directory=str(self.directory_field.stringValue()),
            )
        else:
            return DialogResult(cancelled=True)

    def _create_accessory_view(self) -> NSView:
        """Create the accessory view with labeled fields."""
        # View dimensions
        width = 280
        height = 140
        field_height = 24
        label_height = 17
        spacing = 8
        help_button_size = 16

        view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, width, height))

        y = height - label_height - spacing

        # URL field
        url_label = self._create_label("Amphigory URL:", 0, y, width - help_button_size - spacing)
        view.addSubview_(url_label)

        url_help = self._create_help_button(
            width - help_button_size, y - 2,
            "showUrlHelp:"
        )
        view.addSubview_(url_help)

        y -= field_height + 2
        self.url_field = self._create_text_field(0, y, width, self.initial_url)
        view.addSubview_(self.url_field)

        y -= label_height + spacing + 4

        # Directory field
        dir_label = self._create_label("Amphigory directory:", 0, y, width - help_button_size - spacing)
        view.addSubview_(dir_label)

        dir_help = self._create_help_button(
            width - help_button_size, y - 2,
            "showDirHelp:"
        )
        view.addSubview_(dir_help)

        y -= field_height + 2
        self.directory_field = self._create_text_field(0, y, width, self.initial_directory)
        view.addSubview_(self.directory_field)

        y -= label_height + spacing + 4

        # Wiki link
        if self.wiki_url:
            wiki_button = NSButton.alloc().initWithFrame_(NSMakeRect(0, y - 4, width, 20))
            wiki_button.setTitle_(f"📖 More help and documentation")
            wiki_button.setBezelStyle_(0)  # Borderless
            wiki_button.setBordered_(False)
            wiki_button.setTarget_(self)
            wiki_button.setAction_("openWiki:")
            # Make it look like a link
            wiki_button.setAlignment_(0)  # Left aligned
            view.addSubview_(wiki_button)

        return view

    def _create_label(self, text: str, x: float, y: float, width: float) -> NSTextField:
        """Create a label (non-editable text field)."""
        label = NSTextField.alloc().initWithFrame_(NSMakeRect(x, y, width, 17))
        label.setStringValue_(text)
        label.setBezeled_(False)
        label.setDrawsBackground_(False)
        label.setEditable_(False)
        label.setSelectable_(False)
        label.setFont_(NSFont.systemFontOfSize_(13))
        return label

    def _create_text_field(self, x: float, y: float, width: float, default: str) -> NSTextField:
        """Create an editable text field."""
        field = NSTextField.alloc().initWithFrame_(NSMakeRect(x, y, width, 24))
        field.setStringValue_(default)
        field.setBezeled_(True)
        field.setEditable_(True)
        field.setSelectable_(True)
        return field

    def _create_help_button(self, x: float, y: float, action: str) -> NSButton:
        """Create a help button with click action."""
        button = NSButton.alloc().initWithFrame_(NSMakeRect(x, y, 16, 16))
        button.setBezelStyle_(9)  # NSBezelStyleHelpButton - circular ?
        button.setTitle_("")
        button.setButtonType_(6)  # NSButtonTypeMomentaryPushIn
        button.setTarget_(self)
        button.setAction_(action)
        return button

    def showUrlHelp_(self, sender) -> None:
        """Show help for URL field."""
        alert = NSAlert.alloc().init()
        alert.setMessageText_("Amphigory URL")
        alert.setInformativeText_(
            "Typically something like https://amphigory.my.domain/ or http://localhost:6199/"
        )
        alert.addButtonWithTitle_("OK")
        alert.runModal()

    def showDirHelp_(self, sender) -> None:
        """Show help for directory field."""
        alert = NSAlert.alloc().init()
        alert.setMessageText_("Amphigory directory")
        alert.setInformativeText_("Usually something like /opt/amphigory")
        alert.addButtonWithTitle_("OK")
        alert.runModal()

    def openWiki_(self, sender) -> None:
        """Open wiki URL in browser."""
        if self.wiki_url:
            webbrowser.open(self.wiki_url)
