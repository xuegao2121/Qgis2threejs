# -*- coding: utf-8 -*-
"""
/***************************************************************************
 Q3DWindow

                              -------------------
        begin                : 2016-02-10
        copyright            : (C) 2016 Minoru Akagi
        email                : akaginch@gmail.com
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""
from xml.dom import minidom

from PyQt5.Qt import QMainWindow, QEvent, Qt
from PyQt5.QtCore import QObject, QSettings, QUrl, QVariant, pyqtSignal
from PyQt5.QtGui import QDesktopServices, QIcon
from PyQt5.QtWidgets import QCheckBox, QComboBox, QDialog, QDialogButtonBox, QMessageBox, QProgressBar


from . import q3dconst
from .conf import debug_mode, plugin_version
from .exporttowebdialog import ExportToWebDialog
from .propertypages import WorldPropertyPage, DEMPropertyPage, VectorPropertyPage
from .qgis2threejstools import logMessage, pluginDir
from .ui.propertiesdialog import Ui_PropertiesDialog
from .ui.q3dwindow import Ui_Q3DWindow


class Q3DViewerInterface:

  def __init__(self, qgisIface, wnd, treeView, webView, controller):
    self.qgisIface = qgisIface
    self.wnd = wnd
    self.treeView = treeView
    self.webView = webView

    self.connectToController(controller)

  def connectToController(self, controller):
    self.controller = controller
    controller.connectToIface(self)

  def disconnectFromController(self):
    if self.controller:
      self.controller.disconnectFromIface()
    self.controller = None

  def fetchLayerList(self):
    settings = self.controller.settings
    settings.updateLayerList()
    self.treeView.setLayerList(settings.getLayerList())

  def startApplication(self):
    self.webView.runString("app.start();");

  def setPreviewEnabled(self, enabled):
    self.controller.setPreviewEnabled(enabled)

    elem = "document.getElementById('cover')"
    self.webView.runString("{}.style.display = '{}';".format(elem, "none" if enabled else "block"))
    if not enabled:
      self.webView.runString("{}.innerHTML = '<img src=\"../icon.png\">';".format(elem))

  def loadJSONObject(self, obj):
    # display the content of the object in the debug element
    if debug_mode == 2:
      self.webView.runString("document.getElementById('debug').innerHTML = '{}';".format(str(obj)[:500].replace("'", "\\'")))

    self.webView.bridge.sendData.emit(QVariant(obj))

  def runString(self, string):
    self.webView.runString(string)

  def abort(self):
    self.controller.abort()

  def exportScene(self):
    self.controller.exportScene()

  def exportLayer(self, layer):
    self.controller.exportLayer(layer)

  def showMessage(self, msg):
    self.wnd.ui.statusbar.showMessage(msg)

  def clearMessage(self):
    self.wnd.ui.statusbar.clearMessage()

  def progress(self, percentage=100, text=None):
    bar = self.wnd.ui.progressBar
    if percentage == 100:
      bar.setVisible(False)
      bar.setFormat("")
    else:
      bar.setVisible(True)
      bar.setValue(percentage)
      if text is not None:
        bar.setFormat(text)

  def showWorldPropertiesDialog(self):
    dialog = PropertiesDialog(self.wnd, self.qgisIface, self.controller.settings)
    dialog.propertiesAccepted.connect(self.updateWorldProperties)
    dialog.showWorldProperties()

  def updateWorldProperties(self, _, properties):
    if self.controller.settings.worldProperties() == properties:
      return
    self.controller.settings.setWorldProperties(properties)
    self.controller.layersNeedUpdate = True
    self.controller.updateScene()

  def showLayerPropertiesDialog(self, layer):
    dialog = PropertiesDialog(self.wnd, self.qgisIface, self.controller.settings)    #, pluginManager)
    dialog.propertiesAccepted.connect(self.updateLayerProperties)
    dialog.showLayerProperties(layer)
    return True

  def updateLayerProperties(self, layerId, properties):
    # save layer properties
    layer = self.controller.settings.getItemByLayerId(layerId)
    layer.properties = properties
    layer.updated = True

    if layer.visible:
      self.exportLayer(layer)

  def getDefaultProperties(self, layer):
    dialog = PropertiesDialog(self.wnd, self.qgisIface, self.controller.settings)
    dialog.setLayer(layer)
    return dialog.page.properties()


class Q3DWindow(QMainWindow):

  def __init__(self, parent, qgisIface, controller, isViewer=True):
    QMainWindow.__init__(self, parent)
    self.qgisIface = qgisIface
    self.isViewer = isViewer
    self.settings = controller.settings

    #if live_in_another_process:
    #  self.iface = SocketClient(serverName, self)
    #  self.iface.notified.connect(self.notified)
    #  self.iface.requestReceived.connect(self.requestReceived)
    #  self.iface.responseReceived.connect(self.responseReceived)
    #else:
    #  self.iface = Q3DConnector(self)

    self.setWindowIcon(QIcon(pluginDir("icon.png")))

    self.ui = Ui_Q3DWindow()
    self.ui.setupUi(self)

    self.iface = Q3DViewerInterface(qgisIface, self, self.ui.treeView, self.ui.webView, controller)

    self.setupMenu()
    self.setupStatusBar(self.iface)
    self.ui.treeView.setup(self.iface)
    self.ui.webView.setup(self, self.iface, isViewer)

    self.iface.fetchLayerList()

    # signal-slot connections
    self.ui.actionExportToWeb.triggered.connect(self.exportToWeb)
    self.ui.actionSaveAsImage.triggered.connect(self.saveAsImage)
    self.ui.actionPluginSettings.triggered.connect(self.pluginSettings)
    self.ui.actionWorldSettings.triggered.connect(self.iface.showWorldPropertiesDialog)
    self.ui.actionResetCameraPosition.triggered.connect(self.ui.webView.resetCameraPosition)
    self.ui.actionReload.triggered.connect(self.ui.webView.reloadPage)
    self.ui.actionAlwaysOnTop.toggled.connect(self.alwaysOnTopToggled)
    self.ui.actionHelp.triggered.connect(self.help)
    self.ui.actionHomePage.triggered.connect(self.homePage)
    self.ui.actionSendFeedback.triggered.connect(self.sendFeedback)
    self.ui.actionAbout.triggered.connect(self.about)
    self.ui.lineEditInputBox.returnPressed.connect(self.runInputBoxString)

    # to disconnect from map canvas when window is closed
    self.setAttribute(Qt.WA_DeleteOnClose)

    self.alwaysOnTopToggled(False)

    # restore window geometry and dockwidget layout
    settings = QSettings()
    self.restoreGeometry(settings.value("/Qgis2threejs/wnd/geometry", b""))
    self.restoreState(settings.value("/Qgis2threejs/wnd/state", b""))

  def closeEvent(self, event):
    self.iface.disconnectFromController()

    settings = QSettings()
    settings.setValue("/Qgis2threejs/wnd/geometry", self.saveGeometry())
    settings.setValue("/Qgis2threejs/wnd/state", self.saveState())
    QMainWindow.closeEvent(self, event)

  def keyPressEvent(self, event):
    if event.key() == Qt.Key_Escape:
      self.iface.abort()
    QMainWindow.keyPressEvent(self, event)

  def setupMenu(self):
    self.ui.menuPanels.addAction(self.ui.dockWidgetLayers.toggleViewAction())
    self.ui.menuPanels.addAction(self.ui.dockWidgetConsole.toggleViewAction())

  def setupStatusBar(self, iface):
    w = QProgressBar(self.ui.statusbar)
    w.setObjectName("progressBar")
    w.setMaximumWidth(250)
    w.setAlignment(Qt.AlignCenter)
    w.setVisible(False)
    self.ui.statusbar.addPermanentWidget(w)
    self.ui.progressBar = w

    w = QCheckBox(self.ui.statusbar)
    w.setObjectName("checkBoxPreview")
    w.setText("Preview")     #_translate("Q3DWindow", "Preview"))
    w.setChecked(True)
    self.ui.statusbar.addPermanentWidget(w)
    self.ui.checkBoxPreview = w
    self.ui.checkBoxPreview.toggled.connect(iface.setPreviewEnabled)

  def alwaysOnTopToggled(self, checked):
    if checked:
      self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
    else:
      self.setWindowFlags(self.windowFlags() & ~Qt.WindowStaysOnTopHint)
    self.show()

  def changeEvent(self, event):
    if self.isViewer and event.type() == QEvent.WindowStateChange:
      if self.windowState() & Qt.WindowMinimized:
        self.runString("app.pause();")
      else:
        self.runString("app.resume();")

  #TODO: CopyAction is not possible
  def dragEnterEvent(self, event):
    print(str(event.mimeData().formats()))
    if event.mimeData().hasFormat("application/qgis.layertreemodeldata"):
      event.setDropAction(Qt.CopyAction)
      event.accept()
      # event.acceptProposedAction()

  def dropEvent(self, event):
    print("Possible actions: ".format(int(event.possibleActions()))) # => 2 (Qt.MoveAction)
    event.setDropAction(Qt.CopyAction)
    event.accept()
    #event.ignore()
    #event.setAccepted(False)
    xml = event.mimeData().data("application/qgis.layertreemodeldata").data()
    print(xml)
    # b'<layer_tree_model_data>\n <layer-tree-layer expanded="1" checked="Qt::Checked" id="\xe6\xa8\x99\xe6\xba\x96\xe5\x9c\xb0\xe5\x9b\xb320160213181331361" name="\xe6\xa8\x99\xe6\xba\x96\xe5\x9c\xb0\xe5\x9b\xb3">\n  <customproperties/>\n </layer-tree-layer>\n</layer_tree_model_data>\n'

    doc = minidom.parseString(xml)
    layerId = doc.getElementsByTagName("layer-tree-layer")[0].getAttribute("id")
    print("Layer {0} has been dropped.".format(layerId))
    """
    from PyQt5.QtXml import QDomDocument
    # ImportError: No module named 'PyQt5.QtXml'

    doc = QDomDocument()
    doc.setContent(xml)
    root = doc.documentElement()
    layerId = root.firstChild().toElement().attribute("id").decode("utf-8")
    """

  def clearConsole(self):
    self.ui.listWidgetDebugView.clear()

  def printConsoleMessage(self, message, lineNumber="", sourceID=""):
    self.ui.listWidgetDebugView.addItem("{} ({}): {}".format(sourceID.split("/")[-1], lineNumber, message))

  def runInputBoxString(self):
    self.runString(self.ui.lineEditInputBox.text())

  def runString(self, string):
    self.ui.webView.runString(string)

  def exportToWeb(self):
    dialog = ExportToWebDialog(self, self.qgisIface, self.settings)
    dialog.show()
    dialog.exec_()

  def saveAsImage(self):
    self.runString("app.showPrintDialog();")

  def pluginSettings(self):
    from .pluginsettings import SettingsDialog
    dialog = SettingsDialog(self)
    if dialog.exec_():
      self.iface.controller.pluginManager.reloadPlugins()

  def help(self):
    QDesktopServices.openUrl(QUrl("http://qgis2threejs.readthedocs.io/en/docs-release/"))

  def homePage(self):
    QDesktopServices.openUrl(QUrl("https://github.com/minorua/Qgis2threejs"))

  def sendFeedback(self):
    QDesktopServices.openUrl(QUrl("https://github.com/minorua/Qgis2threejs/issues"))

  def about(self):
    QMessageBox.information(self, "Qgis2threejs Plugin", "Plugin version: {0}".format(plugin_version), QMessageBox.Ok)


class PropertiesDialog(QDialog):

  propertiesAccepted = pyqtSignal(str, dict)

  def __init__(self, parent, qgisIface, settings, pluginManager=None):
    QDialog.__init__(self, parent)
    self.setAttribute(Qt.WA_DeleteOnClose)

    self.iface = qgisIface
    self.pluginManager = pluginManager
    self.settings = settings
    self.mapTo3d = settings.mapTo3d

    self.wheelFilter = WheelEventFilter()

    self.currentItem = None

    # Set up the user interface from Designer.
    self.ui = Ui_PropertiesDialog()
    self.ui.setupUi(self)
    self.ui.buttonBox.clicked.connect(self.buttonClicked)

    # restore dialog geometry
    settings = QSettings()
    self.restoreGeometry(settings.value("/Qgis2threejs/propdlg/geometry", b""))

    #self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
    #self.activateWindow()

  def closeEvent(self, event):
    # save dialog geometry
    settings = QSettings()
    settings.setValue("/Qgis2threejs/propdlg/geometry", self.saveGeometry())
    QDialog.closeEvent(self, event)

  def setLayer(self, layer):
    self.layer = layer
    self.setWindowTitle("Layer Properties - {0} (Qgis2threejs)".format(layer.name))

    if layer.geomType == q3dconst.TYPE_DEM:
      self.page = DEMPropertyPage(self, self)
      self.page.setup(layer)
    elif layer.geomType == q3dconst.TYPE_IMAGE:
      return
    else:
      self.page = VectorPropertyPage(self, self)
      self.page.setup(layer)
    self.ui.scrollArea.setWidget(self.page)

    # disable wheel event for ComboBox widgets
    for w in self.ui.scrollArea.findChildren(QComboBox):
      w.installEventFilter(self.wheelFilter)

  def buttonClicked(self, button):
    role = self.ui.buttonBox.buttonRole(button)
    if role in [QDialogButtonBox.AcceptRole, QDialogButtonBox.ApplyRole]:
      if isinstance(self.page, WorldPropertyPage):
        self.propertiesAccepted.emit("", self.page.properties())
      else:
        self.propertiesAccepted.emit(self.layer.layerId, self.page.properties())

  def showLayerProperties(self, layer):
    self.setLayer(layer)
    self.show()
    self.exec_()

  def showWorldProperties(self):
    self.page = WorldPropertyPage(self, self)
    self.page.setup(self.settings.worldProperties())
    self.ui.scrollArea.setWidget(self.page)
    self.show()
    self.exec_()


class WheelEventFilter(QObject):

  def eventFilter(self, obj, event):
    if event.type() == QEvent.Wheel:
      return True
    return QObject.eventFilter(self, obj, event)
