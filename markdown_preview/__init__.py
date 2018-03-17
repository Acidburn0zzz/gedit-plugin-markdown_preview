import subprocess
import gi
import os
gi.require_version('WebKit2', '4.0')
from gi.repository import GObject, Gtk, Gedit, Gio, PeasGtk, WebKit2, GLib

BASE_PATH = os.path.dirname(os.path.realpath(__file__))
LOCALE_PATH = os.path.join(BASE_PATH, 'locale')

try:
	import gettext
	gettext.bindtextdomain('gedit-plugin-markdown-preview', LOCALE_PATH)
	_ = lambda s: gettext.dgettext('gedit-plugin-markdown-preview', s)
except:
	_ = lambda s: s
	
#################
	
MD_PREVIEW_KEY_BASE = 'org.gnome.gedit.plugins.markdown_preview'
BASE_TEMP_NAME = '/tmp/gedit_plugin_markdown_preview'

class MarkdownGeditPluginApp(GObject.Object, Gedit.AppActivatable):
	__gtype_name__ = 'MarkdownGeditPluginApp'
	app = GObject.property(type=Gedit.App)
	
	def __init__(self):
		GObject.Object.__init__(self)

	def do_activate(self):
		self._build_menu()

	def do_deactivate(self):
		self._remove_menu()
	
	def _build_menu(self):
		self.menu_ext = self.extend_menu('file-section-1')
		menu = Gio.Menu()
		menu_item_export = Gio.MenuItem.new(_("Export the preview"), 'win.export_doc')
		menu_item_print = Gio.MenuItem.new(_("Print the preview"), 'win.print_doc')
		menu.append_item(menu_item_export)
		menu.append_item(menu_item_print)
		self.menu_section = Gio.MenuItem.new_section(_("Markdown Preview"), menu)
		self.menu_ext.append_menu_item(self.menu_section)
	
	def _remove_menu(self):
		self.menu_ext = None
		self.menu_item = None

class MarkdownGeditPluginWindow(GObject.Object, Gedit.WindowActivatable, PeasGtk.Configurable):
	window = GObject.property(type=Gedit.Window)
	__gtype_name__ = 'MarkdownGeditPluginWindow'

	def __init__(self):
		GObject.Object.__init__(self)
		# This is the attachment we will make to bottom panel.
		self.preview_bar = Gtk.Box()
		# This is needed because Python is stupid # FIXME dans le activate ?
		self._auto_reload = False
	
	# This is called every time the gui is updated
	def do_update_state(self):
		if self.window.get_active_view() is not None:
			if self._auto_reload:
				self.on_reload(None, None)
			if self.recognize_format() != 'error':
				self.panel.show()
			elif len(self.panel.get_children()) is 1:
				self.panel.hide()
	
	def do_activate(self):
		# Defining the action which was set earlier in AppActivatable.
		self._handlers = []
		self._settings = Gio.Settings.new(MD_PREVIEW_KEY_BASE)
		self._isAtBottom = (self._settings.get_string('position') == 'bottom')
		self._handlers.append( self._settings.connect('changed::position', self.change_panel) )
		self._is_paginated = False
		self.insert_in_adequate_panel()
		self._handlers.append( self.window.connect('active-tab-changed', self.on_reload) )
		self._page_index = 0
		self.temp_file_md = Gio.File.new_for_path(BASE_TEMP_NAME + '.md')
		self._connect_menu()
		self.window.lookup_action('export_doc').set_enabled(False)
		self.window.lookup_action('print_doc').set_enabled(False)
				
	def do_deactivate(self):
		self._settings.disconnect(self._handlers[0])
		self.window.disconnect(self._handlers[1])		
		self.delete_temp_file()
		self._remove_from_panel()

	def _connect_menu(self):
		action_export = Gio.SimpleAction(name='export_doc')
		action_print = Gio.SimpleAction(name='print_doc')
		action_export.connect('activate', self.export_doc)
		action_print.connect('activate', self.print_doc)
		self.window.add_action(action_export)
		self.window.add_action(action_print)
		
	def insert_in_adequate_panel(self):
		# This is the preview itself
		self._webview = WebKit2.WebView()
		
		# Building the interface
		zoom_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
		self.pages_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
		toggle_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
		insert_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
		
		main_box = Gtk.Box(margin_left=5, margin_right=5, margin_top=5, margin_bottom=5, spacing=2)
		
		if self._isAtBottom:
			self.preview_bar.props.orientation = Gtk.Orientation.HORIZONTAL
			main_box.props.orientation = Gtk.Orientation.VERTICAL
			main_box.props.homogeneous = True
			
		else:
			self.preview_bar.props.orientation = Gtk.Orientation.VERTICAL
			main_box.props.orientation = Gtk.Orientation.HORIZONTAL
			main_box.props.homogeneous = False
		
		insertBtn = self.build_button('clicked', 'insert-image-symbolic')
		insertBtn.connect('clicked', self.on_insert)
		insert_box.pack_end(insertBtn, expand=True, fill=True, padding=0)

		refreshBtn = self.build_button('toggled', 'view-refresh-symbolic')
		refreshBtn.connect('toggled', self.on_set_reload)
		toggle_box.pack_start(refreshBtn, expand=False, fill=True, padding=0)

		paginatedBtn = self.build_button('toggled', 'x-office-presentation-symbolic')
		paginatedBtn.connect('toggled', self.on_set_paginated)
		toggle_box.pack_end(paginatedBtn, expand=False, fill=True, padding=0)
		
		zoomInBtn = self.build_button('clicked', 'zoom-in-symbolic')
		zoomInBtn.connect('clicked', self.on_zoom_in)
		zoom_box.add(zoomInBtn)
		
		zoomOutBtn = self.build_button('clicked', 'zoom-out-symbolic')
		zoomOutBtn.connect('clicked', self.on_zoom_out)
		zoom_box.add(zoomOutBtn)
		
		previousBtn = self.build_button('clicked', 'go-previous-symbolic')
		previousBtn.connect('clicked', self.on_previous_page)
		self.pages_box.add(previousBtn)
		
		nextBtn = self.build_button('clicked', 'go-next-symbolic')
		nextBtn.connect('clicked', self.on_next_page)
		self.pages_box.add(nextBtn)
		
		main_box.pack_start(zoom_box, expand=False, fill=False, padding=0)
		main_box.pack_start(self.pages_box, expand=False, fill=False, padding=0)
		main_box.pack_end(toggle_box, expand=False, fill=False, padding=0)
		main_box.pack_end(insert_box, expand=False, fill=False, padding=0)

		# main_box only contains the buttons, it will pack at the end (bottom or right) of
		# the preview_bar object, where the webview has already been added.
		self.preview_bar.pack_end(main_box, expand=False, fill=False, padding=0)
		self.preview_bar.pack_start(self._webview, expand=True, fill=True, padding=0)
		
		self.show_on_panel()

	def build_button(self, mode, icon):
		if mode is 'toggled':
			btn = Gtk.ToggleButton()
		else:
			btn = Gtk.Button()
		image = Gtk.Image()
		image.set_from_icon_name(icon, Gtk.IconSize.BUTTON)
		btn.add(image)
		return btn
	
	def on_set_reload(self, btn):
		if btn.get_active():
			self._auto_reload = True
			self.on_reload(None, None)
		else:
			self._auto_reload = False

	def on_set_paginated(self, btn):
		if btn.get_active():
			self._is_paginated = True
			self.pages_box.props.visible = True
			self.on_reload(None, None)
		else:
			self._is_paginated = False
			self.pages_box.props.visible = False
			self.on_reload(None, None)
	
	def on_previous_page(self, btn):
		if self._page_index > 0:
			self._page_index = self._page_index -1
			self.on_reload(None, None)
		else:
			btn.active = False
			
	def on_next_page(self, btn):
		self._page_index = self._page_index +1
		self.on_reload(None, None)
	
	def delete_temp_file(self):
		if self.temp_file_md.query_exists():
			self.temp_file_md.delete()
	
	def recognize_format(self):
		doc = self.window.get_active_document()
		
		# It will not load documents which are not .md
		name = doc.get_short_name_for_display()
		temp = name.split('.')
		if temp[len(temp)-1] == 'md':
			return 'md'
		elif temp[len(temp)-1] == 'html':
			return 'html'
		else:
			# The current content is not replaced, which allows document consulation while working on a file
			self.window.lookup_action('export_doc').set_enabled(False)
			self.window.lookup_action('print_doc').set_enabled(False)
			return 'error'
	
	# This needs dummy parameters because it's connected to a signal which give arguments.
	def on_reload(self, osef, oseb):
	
		# Guard clause: it will not load documents which are not .md
		if self.recognize_format() is 'error':
			return
		elif self.recognize_format() is 'html':
			doc = self.window.get_active_document()
			start, end = doc.get_bounds()
			html_string = doc.get_text(start, end, True)
			pre_string = '<html><head><meta charset="utf-8" /></head><body>'
			post_string = '</body></html>'
			html_string = self.current_page(html_string)
			html_content = pre_string + html_string + post_string
		else:
			# Get the current document, or the temporary document if requested
			doc = self.window.get_active_document()
			if self._auto_reload:
				start, end = doc.get_bounds()
				unsaved_text = doc.get_text(start, end, True)
				f = open(BASE_TEMP_NAME + '.md', 'w')
				f.write(unsaved_text)
				f.close()
				file_path = self.temp_file_md.get_path()
			else:
				file_path = doc.get_location().get_path()
			
			# It uses pandoc to produce the html code
			pre_string = '<html><head><meta charset="utf-8" /><link rel="stylesheet" href="' + \
				self._settings.get_string('style') + '" /></head><body>'
			post_string = '</body></html>'
			result = subprocess.run(['pandoc', file_path], stdout=subprocess.PIPE)
			html_string = result.stdout.decode('utf-8')
			html_string = self.current_page(html_string)
			html_content = pre_string + html_string + post_string
		
		# The html code is converted into bytes
		my_string = GLib.String()
		my_string.append(html_content)
		bytes_content = my_string.free_to_bytes()
		
		# This uri will be used as a reference for links and images using relative paths
		dummy_uri = self.get_dummy_uri()
		
		# The content is loaded
		self._webview.load_bytes(bytes_content, 'text/html', 'UTF-8', dummy_uri)
		
		self.window.lookup_action('export_doc').set_enabled(True)
		self.window.lookup_action('print_doc').set_enabled(True)
	
	def current_page(self, html_string):
	
		# Guard clause
		if not self._is_paginated:
			return html_string
		
		html_pages = html_string.split('<hr />')
		if self._page_index is len(html_pages):
			self._page_index = self._page_index -1
		html_current_page = html_pages[self._page_index]
		return html_current_page
	
	def get_dummy_uri(self):
		# Support for relative paths is cool, but breaks CSS in many cases
		if self._settings.get_boolean('relative'):
			return self.window.get_active_document().get_location().get_uri()
		else:
			return 'file://'
	
	def show_on_panel(self):
		# Get the bottom bar (A Gtk.Stack), or the side bar, and add our bar to it.
		if self._isAtBottom:
			self.panel = self.window.get_bottom_panel()
		else:
			self.panel = self.window.get_side_panel()
		self.panel.add_titled(self.preview_bar, 'markdown_preview', _("Markdown Preview"))
		self.preview_bar.show_all()
		self.panel.set_visible_child(self.preview_bar)
		self.pages_box.props.visible = self._is_paginated
#		if self.window.get_active_view() is not None:
		if self.window.get_state() is 'STATE_NORMAL':
			self.on_reload(None, None)

	def _remove_from_panel(self):
		self.panel.remove(self.preview_bar)
	
	def on_zoom_in(self, a):
		if self._webview.get_zoom_level() < 10:
			self._webview.set_zoom_level(self._webview.get_zoom_level() + 0.1)
		
	def on_zoom_out(self, a):
		if self._webview.get_zoom_level() > 0.15:
			self._webview.set_zoom_level(self._webview.get_zoom_level() - 0.1)
		
	def on_insert(self, a):
		# Guard clause: it will not load dialog if the file is not .md
		if self.recognize_format() != 'md':
			return
		
		# Building a FileChooserDialog for pictures
		file_chooser = Gtk.FileChooserDialog(_("Select a picture"), self.window,
			Gtk.FileChooserAction.OPEN,
			(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
			Gtk.STOCK_OPEN, Gtk.ResponseType.OK))
		onlyPictures = Gtk.FileFilter()
		onlyPictures.set_name("Pictures")
		onlyPictures.add_mime_type('image/*')
		file_chooser.set_filter(onlyPictures)
		response = file_chooser.run()
		
		# It gets the chosen file's path
		if response == Gtk.ResponseType.OK:
			doc = self.window.get_active_document()
			picture_path = '![](' + file_chooser.get_filename() + ')'
			iter = doc.get_iter_at_mark(doc.get_insert())
			doc.insert(iter, picture_path)
		file_chooser.destroy()
	
	def change_panel(self, a, b):
		self._remove_from_panel()
		self.preview_bar = Gtk.Box()
		self._isAtBottom = (self._settings.get_string('position') == 'bottom')
		self.insert_in_adequate_panel()
	
	def do_create_configure_widget(self):
		# Just return your box, PeasGtk will automatically pack it into a box and show it.
		widget = MdConfigWidget(self.plugin_info.get_data_dir())
		return widget.get_box()

	def export_doc(self, a, b):
		file_chooser = Gtk.FileChooserDialog(_("Export the preview"), self.window,
			Gtk.FileChooserAction.SAVE,
			(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
			Gtk.STOCK_SAVE, Gtk.ResponseType.OK))
		response = file_chooser.run()
		
		# It gets the chosen file's path
		if response == Gtk.ResponseType.OK:
			if file_chooser.get_filename().split('.')[-1] is 'html':
				subprocess.run(['pandoc', self.window.get_active_document().get_location().get_path(), '-o', file_chooser.get_filename()])
			else: # in the future it shall behave differently
				subprocess.run(['pandoc', self.window.get_active_document().get_location().get_path(), '-o', file_chooser.get_filename()])
		file_chooser.destroy()
		
	def print_doc(self, a, b):
		p = WebKit2.PrintOperation.new(self._webview)
		p.run_dialog()

############################

class MdConfigWidget:

	def __init__(self, datadir):
		self._settings = Gio.Settings.new(MD_PREVIEW_KEY_BASE)
		self._settings.get_string('position')
		self._settings.get_boolean('relative')
		self._settings.get_string('style')
		
		self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=20, \
			margin_left=20,margin_right=20,margin_top=20,margin_bottom=20,homogeneous=True)
		#--------
		positionSettingBox=Gtk.Box()
		positionSettingBox.props.spacing = 20
		positionSettingBox.props.orientation = Gtk.Orientation.HORIZONTAL
		positionSettingBox.pack_start(Gtk.Label(_("Preview position")), expand=False, fill=False, padding=0)
		positionCombobox = Gtk.ComboBoxText()
		positionCombobox.append('side', _("Side panel"))
		positionCombobox.append('bottom', _("Bottom panel"))
		positionCombobox.set_active_id(self._settings.get_string('position'))
		positionCombobox.connect('changed', self.on_position_changed)
		positionSettingBox.pack_end(positionCombobox, expand=False, fill=False, padding=0)
		#--------
		relativePathsSettingBox=Gtk.Box()
		relativePathsSettingBox.props.spacing = 20
		relativePathsSettingBox.props.orientation = Gtk.Orientation.HORIZONTAL
		relativePathsSettingBox.pack_start(Gtk.Label(_("Use relative paths")), expand=False, fill=False, padding=0)
		relativePathsSwitch = Gtk.Switch()
		relativePathsSwitch.set_state(self._settings.get_boolean('relative'))
		relativePathsSwitch.connect('notify::active', self.on_relative_changed)
		relativePathsSettingBox.pack_end(relativePathsSwitch, expand=False, fill=False, padding=0)
		#--------
		styleSettingBox=Gtk.Box()
		styleSettingBox.props.spacing = 20
		styleSettingBox.props.orientation = Gtk.Orientation.HORIZONTAL
		styleSettingBox.pack_start(Gtk.Label(_("Stylesheet")), expand=False, fill=False, padding=0)
		self.styleLabel = Gtk.Label(self._settings.get_string('style'))
		styleButton = Gtk.Button()
		styleButton.connect('clicked', self.on_choose_css)
		styleImage = Gtk.Image()
		styleImage.set_from_icon_name('document-open-symbolic', Gtk.IconSize.BUTTON)
		styleButton.add(styleImage)
		styleSettingBox.pack_end(styleButton, expand=False, fill=False, padding=0)
		styleSettingBox.pack_end(self.styleLabel, expand=False, fill=False, padding=0)
		#--------
		self.box.add(positionSettingBox)
		self.box.add(relativePathsSettingBox)
		self.box.add(styleSettingBox)
	
	def get_box(self):
		return self.box
		
	def on_position_changed(self, w):
		self._settings.set_string('position', w.get_active_id())
		
	def on_choose_css(self, w):
		# Building a FileChooserDialog for CSS
		file_chooser = Gtk.FileChooserDialog(_("Select a CSS file"), None, # FIXME
			Gtk.FileChooserAction.OPEN,
			(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
			Gtk.STOCK_OPEN, Gtk.ResponseType.OK))
		onlyCSS = Gtk.FileFilter()
		onlyCSS.set_name(_("Stylesheet"))
		onlyCSS.add_mime_type('text/css')
		file_chooser.set_filter(onlyCSS)
		response = file_chooser.run()
		
		# It gets the chosen file's path
		if response == Gtk.ResponseType.OK:
			self.styleLabel.label = file_chooser.get_filename()
			self._settings.set_string('style', file_chooser.get_filename())
		file_chooser.destroy()
		
	def on_relative_changed(self, w, a):
		if w.get_state():
			self._settings.set_boolean('relative', True)
		else:
			self._settings.set_boolean('relative', False)
	
