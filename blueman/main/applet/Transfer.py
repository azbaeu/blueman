# coding=utf-8
# Copyright (C) 2008 Valmantas Paliksa <walmis at balticum-tv dot lt>
# Copyright (C) 2008 Tadas Dailyda <tadas at dailyda dot com>
#
# Licensed under the GNU General Public License Version 3
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
# 
from blueman.main.SpeedCalc import SpeedCalc
from blueman.main.Config import Config
from blueman.ods.OdsManager import OdsManager
from blueman.main.Device import Device
from blueman.Functions import *
from subprocess import call
import os
import pynotify
import gettext
import gobject

_ = gettext.gettext

class Transfer(OdsManager):

	def __init__(self, applet):
		OdsManager.__init__(self)
		self.Applet = applet
		self.GHandle("server-created", self.on_server_created)
		self.transfers = {}
		self.Config = Config("transfer")
		

		#check options
		if self.Config.props.opp_enabled == None:
			self.Config.props.opp_enabled = True
		
		if self.Config.props.ftp_enabled == None:
			self.Config.props.ftp_enabled = True
			
		self.start_server("opp")
		self.start_server("ftp")

		
	def start_server(self, pattern):
		print "Start", pattern
		if pattern == "opp":
			if self.Config.props.opp_enabled:
				self.create_server()
		elif pattern == "ftp":
			if self.Config.props.ftp_enabled:
				self.create_server(pattern="ftp", require_pairing=True)
		
	def on_server_created(self, inst, server, pattern):
		def on_started(server):
			print pattern, "Started"
			
		def on_session_created(server, session):
			print pattern, "session created"
			if pattern != "opp":
				return
			
			def on_transfer_started(session, filename, local_path, total_bytes):
				print local_path
				def on_cancel(n, action):
					session.Cancel()
					print "cancel"
				
				def access_cb(n, action):
					t = self.transfers[session.object_path]
					
					if t["waiting"]:
						if action == "accept":
							session.Accept()
						else:
							session.Reject()
						
						if not t["notification"] == None:
							t["waiting"] = False
							print "clearing actions"
							n.clear_actions()
							n.add_action("cancel", _("Cancel"), on_cancel)
							n.set_urgency(pynotify.URGENCY_NORMAL)
							n.set_timeout(0)
							
							update_notification(n)
					
				def on_closed(n):
					t = self.transfers[session.object_path]
					if t["waiting"]:
						session.Reject()
					
					if not self.transfers[session.object_path]["finished"]:
						gobject.source_remove(self.transfers[session.object_path]["updater"])
						self.transfers[session.object_path]["notification"] = None
					
						


				def show_open():
					temp = []
					def on_open(n, action):
						print "open", path
						call(["xdg-open", local_path])
						temp.remove(n)
					
					n = pynotify.Notification(_("File Saved"), _("Would you like to open %s?") % filename)
					n.set_icon_from_pixbuf(get_icon("gtk-save", 48))
					n.add_action("open", _("Open"), on_open)
					n.attach_to_status_icon(self.Applet.status_icon)
					n.show()
					temp.append(n)
					return n

						
				def update_notification(n):
					t = self.transfers[session.object_path]

					if not t["waiting"]:
						if t["finished"]:
							if t["transferred"] == t["total"]:
								show_open()
							n.disconnect(closed_sig)
							
							gobject.source_remove(self.transfers[session.object_path]["updater"])
							
							del self.transfers[session.object_path]
							
							n.close()
							
							return False
						
						else:
							
							spd = format_bytes(t["calc"].calc(t["transferred"]))
							trans = format_bytes(t["transferred"])
							tot = format_bytes(t["total"])
		
							n.update("Receiving File", "Receiving File %s\n%.2f%s out of %.2f%s (%.2f%s/s)" % (t["filename"],trans[0], trans[1], tot[0], tot[1], spd[0], spd[1]))
							n.show()
					
					return True
						
				
				info = server.GetServerSessionInfo(session.object_path)

				try:
					dev = self.Applet.Manager.FindDevice(info["BluetoothAddress"])
					dev = Device(dev)
					name = dev.Alias
					dev.Destroy()
				except:
					name = info["BluetoothAddress"]
				
				icon = composite_icon(get_icon("blueman-send-file", 48), [(get_icon("blueman", 24), 24, 24, 255)])
				n = pynotify.Notification(_("Incoming File"), _("Incoming file %s from %s") % (os.path.basename(filename), name))
				n.set_icon_from_pixbuf(icon)
				n.set_category("bluetooth.transfer")
				n.attach_to_status_icon(self.Applet.status_icon)
				n.add_action("accept", _("Accept"), access_cb)
				n.add_action("reject", _("Reject"), access_cb)
				n.add_action("default", "Default Action", access_cb)
				n.show()
				closed_sig = n.connect("closed", on_closed)
				
				self.transfers[session.object_path] = {}
				self.transfers[session.object_path]["notification"] = n
				self.transfers[session.object_path]["filename"] = filename
				self.transfers[session.object_path]["total"] = total_bytes
				self.transfers[session.object_path]["finished"] = False
				self.transfers[session.object_path]["waiting"] = True
				self.transfers[session.object_path]["calc"] = SpeedCalc()
				self.transfers[session.object_path]["updater"] = gobject.timeout_add(1000, update_notification, n)
				
				def transfer_progress(session, bytes_transferred):
					#print "progress", bytes_transferred
					self.transfers[session.object_path]["transferred"] = bytes_transferred
					
				def transfer_finished(session, type):
					print "---", type
					try:
						if not self.transfers[session.object_path]["finished"]:
							self.transfers[session.object_path]["finished"] = True
							update_notification(n)
					except KeyError:
						pass
						
					
				session.GHandle("transfer-progress", transfer_progress)
				session.GHandle("cancelled", transfer_finished, "cancelled")
				session.GHandle("disconnected", transfer_finished, "disconnected")
				session.GHandle("transfer-completed", transfer_finished, "completed")
				session.GHandle("error-occured", transfer_finished, "error")
				
			session.GHandle("transfer-started", on_transfer_started)
		
		server.GHandle("started", on_started)
		server.GHandle("session-created", on_session_created)
		
		
		if self.Config.props.shared_path == None:
			self.Config.props.shared_path = os.path.expanduser("~")
			
		if self.Config.props.shared_path == None:
			self.Config.props.shared_path = os.path.expanduser("~")
		
		if pattern == "opp":
			server.Start(self.Config.props.opp_shared_path, True, False)
		elif pattern == "ftp":
			if self.Config.props.ftp_allow_write == None:
				self.Config.props.ftp_allow_write = False
			
			server.Start(self.Config.props.ftp_shared_path, self.Config.props.ftp_allow_write, True)
		
	def on_server_destroyed(self, inst, server):
		pass
