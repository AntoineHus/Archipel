# 
# archipelVirtualMachine.py
# 
# Copyright (C) 2010 Antoine Mercadal <antoine.mercadal@inframonde.eu>
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
# 
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.



"""
Contains ArchipelVirtualMachine, the XMPP capable controller

This module contain the class ArchipelVirtualMachine that represents a virtual machine
linked to a libvirt domain and allowing other XMPP entities to control it using IQ.

The ArchipelVirtualMachine is able to register to any kind of XMPP compliant Server. These 
Server SHOULD allow in-band registration, or you have to manually register VM before 
launching them.

Also the JID of the virtual machine MUST be the UUID use in the libvirt domain, or it will
fail.
"""
import xmpp
import libvirt
import sys
import socket
import os
import commands
from utils import *
from archipelBasicXMPPClient import *

VIR_DOMAIN_NOSTATE	                        =	0;
VIR_DOMAIN_RUNNING	                        =	1;
VIR_DOMAIN_BLOCKED	                        =	2;
VIR_DOMAIN_PAUSED	                        =	3;
VIR_DOMAIN_SHUTDOWN	                        =	4;
VIR_DOMAIN_SHUTOFF	                        =	5;
VIR_DOMAIN_CRASHED	                        =	6;

NS_ARCHIPEL_VM_CONTROL      = "trinity:vm:control"
NS_ARCHIPEL_VM_DEFINITION   = "trinity:vm:definition"
#NS_ARCHIPEL_VM_DISK         = "trinity:vm:disk"

class TNArchipelVirtualMachine(TNArchipelBasicXMPPClient):
    """
    this class represent an Virtual Machine, XMPP Capable.
    this class need to already have 
    """
    
    ######################################################################################################
    ###  Super methods overrided
    ######################################################################################################
    
    def __init__(self, jid, password, hypervisor, configuration):
        TNArchipelBasicXMPPClient.__init__(self, jid, password, configuration)
        self.libvirt_connection = None;
        self.register_actions_to_perform_on_auth("set_vcard_entity_type", "virtualmachine")
        self.register_actions_to_perform_on_auth("connect_libvirt", None)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('google.com', 0));
        ipaddr, other = s.getsockname();
        self.hypervisor = hypervisor;
        
        if not os.path.isdir(self.vm_disk_base_path + jid):
            os.mkdir(self.vm_disk_base_path + jid);
                
        self.ipaddr = ipaddr;
    
    
    def register_handler(self):
        """
        this method registers the events handlers.
        it is invoked by super class __xmpp_connect() method
        """
        self.xmppclient.RegisterHandler('iq', self.__process_iq_trinity_control, typ=NS_ARCHIPEL_VM_CONTROL)
        self.xmppclient.RegisterHandler('iq', self.__process_iq_trinity_definition, typ=NS_ARCHIPEL_VM_DEFINITION)
        #self.xmppclient.RegisterHandler('iq', self.__process_iq_trinity_disk, typ=NS_ARCHIPEL_VM_DISK)
        
        TNArchipelBasicXMPPClient.register_handler(self)
    
    
    def disconnect(self):
        """
        Close the connections to libvirt and XMPP server. it overrides the super class 
        method in order to connect also from libvirt
        """
        self.xmppclient.disconnect()
        if self.libvirt_connection:
            self.libvirt_connection.close() 
    
    
    def remove_own_folder(self):
        """
        remove the folder of the virtual with all its contents
        """
        path = self.vm_disk_base_path + str(self.jid);
        os.system("rm -rf " + path);
    
    
    
    ######################################################################################################
    ### Libvirt bindings
    ###################################################################################################### 
    
    def connect_libvirt(self):
        """
        Initialize the connection to the libvirt first, and
        then to the domain by looking the uuid used as JID Node
        
        exit on any error.
        """
        self.domain = None;
        self.libvirt_connection = None;
        
        self.uuid = self.jid.getNode()
        self.libvirt_connection = libvirt.open(None)
        if self.libvirt_connection == None:
            log(self, LOG_LEVEL_ERROR, "unable to connect hypervisor")
            sys.exit(0) 
        log(self, LOG_LEVEL_INFO, "connected to hypervisor using libvirt")
        
        try:
            self.domain = self.libvirt_connection.lookupByUUIDString(self.uuid)
            log(self, LOG_LEVEL_INFO, "sucessfully connect to domain uuid {0}".format(self.uuid))
            
            dominfo = self.domain.info()
            if dominfo[0] == VIR_DOMAIN_RUNNING:
                self.change_presence("", "shutdown");
            elif dominfo[0] == VIR_DOMAIN_PAUSED:
                self.change_presence("away", "shutdown");
            elif dominfo[0] == VIR_DOMAIN_SHUTOFF or dominfo[0] == VIR_DOMAIN_SHUTDOWN:
                self.change_presence("xa", "shutdown");
            
        except libvirt.libvirtError as ex:
            log(self, LOG_LEVEL_ERROR, "Exception raised #{0} : {1}".format(ex.get_error_code(), ex))
            self.change_presence("dnd", "shutdown");
            return
        except:
            log(self, LOG_LEVEL_ERROR, "unexpected exception")
            sys.exit(0)
    
    
    def __create(self, iq):
        """
        Create a domain using libvirt connection
        
        @type iq: xmpp.Protocol.Iq
        @param iq: the received IQ
        
        @rtype: xmpp.Protocol.Iq
        @return: a ready to send IQ containing the result of the action
        """
        reply = None
        try:
            self.domain.create()
            reply = iq.buildReply('success')
            payload = xmpp.Node("domain", attrs={"id": str(self.domain.ID())})
            reply.setQueryPayload([payload])
            log(self, LOG_LEVEL_INFO, "virtual machine created")
            self.change_presence("", "Running");
            self.push_change("virtualmachine-created")
        except libvirt.libvirtError as ex:
            log(self, LOG_LEVEL_ERROR, "exception raised is : {0}".format(ex))
            reply = iq.buildReply('error')
            payload = xmpp.Node("error", attrs={"code": str(ex.get_error_code())})
            payload.addData(str(ex))
            reply.setQueryPayload([payload])
        return reply
    
    
    def __shutdown(self, iq):
        """
        Shutdown a domain using libvirt connection
        
        @type iq: xmpp.Protocol.Iq
        @param iq: the received IQ
        
        @rtype: xmpp.Protocol.Iq
        @return: a ready to send IQ containing the result of the action
        """
        reply = None
        try:
            self.domain.shutdown()
            reply = iq.buildReply('success')
            log(self, LOG_LEVEL_INFO, "virtual machine shutdowned")
            self.change_presence("xa", "shutdown");
            self.push_change("virtualmachine-shutdowned")
        except libvirt.libvirtError as ex:
            log(self, LOG_LEVEL_ERROR, "exception raised is : {0}".format(ex))
            reply = iq.buildReply('error')
            payload = xmpp.Node("error", attrs={"code": str(ex.get_error_code())})
            payload.addData(str(ex))
            reply.setQueryPayload([payload])
        return reply
    
    
    def __reboot(self, iq):
        """
        Reboot a domain using libvirt connection
        
        @type iq: xmpp.Protocol.Iq
        @param iq: the received IQ
        
        @rtype: xmpp.Protocol.Iq
        @return: a ready to send IQ containing the result of the action
        """
        reply = None
        try:
            self.domain.reboot(0) # flags not used in libvirt but required.
            reply = iq.buildReply('success')
            log(self, LOG_LEVEL_INFO, "virtual machine rebooted")
            self.push_change("virtualmachine-rebooted")
        except libvirt.libvirtError as ex:
            log(self, LOG_LEVEL_ERROR, "exception raised is : {0}".format(ex))
            reply = iq.buildReply('error')
            payload = xmpp.Node("error", attrs={"code": str(ex.get_error_code())})
            payload.addData(str(ex))
            reply.setQueryPayload([payload])
        return reply
    
    
    def __suspend(self, iq):
        """
        Suspend (pause) a domain using libvirt connection
        
        @type iq: xmpp.Protocol.Iq
        @param iq: the received IQ
        
        @rtype: xmpp.Protocol.Iq
        @return: a ready to send IQ containing the result of the action
        """
        reply = None
        try:
            self.domain.suspend()
            reply = iq.buildReply('success')
            log(self, LOG_LEVEL_INFO, "virtual machine suspended")
            self.change_presence("away", "paused");
            self.push_change("virtualmachine-suspended")
        except libvirt.libvirtError as ex:
            log(self, LOG_LEVEL_ERROR, "exception raised is : {0}".format(ex))
            reply = iq.buildReply('error')
            payload = xmpp.Node("error", attrs={"code": str(ex.get_error_code())})
            payload.addData(str(ex))
            reply.setQueryPayload([payload])
        return reply
    
    
    def __resume(self, iq):
        """
        Resume (unpause) a domain using libvirt connection
        
        @type iq: xmpp.Protocol.Iq
        @param iq: the received IQ
        
        @rtype: xmpp.Protocol.Iq
        @return: a ready to send IQ containing the result of the action
        """
        reply = None
        try:
            self.domain.resume()
            reply = iq.buildReply('success')
            log(self, LOG_LEVEL_INFO, "virtual machine resumed")
            self.change_presence("", "running");
            self.push_change("virtualmachine-resumed")
        except libvirt.libvirtError as ex:
            log(self, LOG_LEVEL_ERROR, "exception raised is : {0}".format(ex))
            reply = iq.buildReply('error')
            payload = xmpp.Node("error", attrs={"code": str(ex.get_error_code())})
            payload.addData(str(ex))
            reply.setQueryPayload([payload])
        return reply
    
    
    def __info(self, iq):
        """
        Return an IQ containing the info of the domain using libvirt connection
        
        @type iq: xmpp.Protocol.Iq
        @param iq: the received IQ
        
        @rtype: xmpp.Protocol.Iq
        @return: a ready to send IQ containing the result of the action
        """
        reply = None
        try:
            reply = iq.buildReply('success')
            if self.domain:
                dominfo = self.domain.info()
                response = xmpp.Node(tag="info", attrs={"state": dominfo[0], "maxMem": dominfo[1], "memory": dominfo[2], "nrVirtCpu": dominfo[3], "cpuTime": dominfo[4]})
                reply.setQueryPayload([response])
                log(self, LOG_LEVEL_DEBUG, "virtual machine info sent")
            else:
                reply = iq.buildReply('error')
        except libvirt.libvirtError as ex:
            log(self, LOG_LEVEL_ERROR, "exception raised is : {0}".format(ex))
            reply = iq.buildReply('error')
            payload = xmpp.Node("error", attrs={"code": str(ex.get_error_code())})
            payload.addData(str(ex))
            reply.setQueryPayload([payload])
                
        except Exception as ex:
            log(self, LOG_LEVEL_ERROR, "exception raised is : {0}".format(ex))
            reply = iq.buildReply('error')
            reply.setQueryPayload([str(ex)])
        return reply
    
    
    def __define(self, iq):
        """
        Define a virtual machine in the libvirt according to the XML data
        domain passed in argument
        
        @type iq: xmpp.Protocol.Iq
        @param iq: the received IQ
        
        @rtype: xmpp.Protocol.Iq
        @return: a ready to send IQ containing the result of the action
        """
        reply = None
        
        try :
            domain_node = xmpp.simplexml.XML2Node(str(iq.getQueryPayload()[0]));
            domain_uuid = domain_node.getTag("uuid").getData()
            if domain_uuid != self.jid.getNode():
                log(self, LOG_LEVEL_ERROR, "given UUID {0} doesn't match JID {1}".format(domain_uuid, self.jid.getNode()))
                reply = iq.buildReply('error')
                return reply
        except Exception as ex:
            log(self, LOG_LEVEL_ERROR, "exception raised is : {0}".format(ex))
            reply = iq.buildReply('error')
            reply.setQueryPayload([str(ex)])
            return reply 
            
        try:
            reply = iq.buildReply('success')
            self.libvirt_connection.defineXML(str(iq.getQueryPayload()[0]))
            log(self, LOG_LEVEL_INFO, "virtual machine XML is defined")
            if not self.domain:
                self.connect_libvirt()
            self.push_change("virtualmachine-defined")
        except libvirt.libvirtError as ex:
            log(self, LOG_LEVEL_ERROR, "exception raised is : {0}".format(ex))
            reply = iq.buildReply('error')
            payload = xmpp.Node("error", attrs={"code": str(ex.get_error_code())})
            payload.addData(str(ex))
            reply.setQueryPayload([payload])
        return reply
    
    
    def __undefine(self, iq):
        """
        Undefine a virtual machine in the libvirt according to the XML data
        domain passed in argument
        
        @type iq: xmpp.Protocol.Iq
        @param iq: the received IQ
        
        @rtype: xmpp.Protocol.Iq
        @return: a ready to send IQ containing the result of the action
        """
        reply = None
        try:
            reply = iq.buildReply('success')
            self.domain.undefine()
            log(self, LOG_LEVEL_INFO, "virtual machine is undefined")
            self.push_change("virtualmachine-undefined")
        except libvirt.libvirtError as ex:
            log(self, LOG_LEVEL_ERROR, "exception raised is : {0}".format(ex))
            reply = iq.buildReply('error')
            payload = xmpp.Node("error", attrs={"code": str(ex.get_error_code())})
            payload.addData(str(ex))
            reply.setQueryPayload([payload])
        return reply
    
    
    def __vncdisplay(self, iq):
        """
        get the VNC display used in the virtual machine.
        
        @type iq: xmpp.Protocol.Iq
        @param iq: the received IQ
        
        @rtype: xmpp.Protocol.Iq
        @return: a ready to send IQ containing the result of the action
        """
        reply = None
        try:
            reply = iq.buildReply('success')                
            xmldesc = self.domain.XMLDesc(0);
            xmldescnode = xmpp.simplexml.NodeBuilder(data=xmldesc).getDom();
            graphicnode = xmldescnode.getTag(name="devices").getTag(name="graphics");
            payload = xmpp.Node("vncdisplay", attrs={"port": str(graphicnode.getAttr("port")), "host": self.ipaddr})
            reply.setQueryPayload([payload])
        except libvirt.libvirtError as ex:
            log(self, LOG_LEVEL_ERROR, "exception raised is : {0}".format(ex))
            reply = iq.buildReply('error')
            payload = xmpp.Node("error", attrs={"code": str(ex.get_error_code())})
            payload.addData(str(ex))
            reply.setQueryPayload([payload])
        except Exception as ex:
            log(self, LOG_LEVEL_ERROR, "exception raised is : {0}".format(ex))
            reply = iq.buildReply('error')
            reply.setQueryPayload([str(ex)])
        return reply
    
    
    def __xml_description(self, iq):
        """
        get the XML Desc of the virtual machine.
        
        @type iq: xmpp.Protocol.Iq
        @param iq: the received IQ
        
        @rtype: xmpp.Protocol.Iq
        @return: a ready to send IQ containing the result of the action
        """
        reply = None
        try:
            reply = iq.buildReply('success')
            xmldesc = self.domain.XMLDesc(0);
            xmldescnode = xmpp.simplexml.NodeBuilder(data=xmldesc).getDom();
            reply.setQueryPayload([xmldescnode])
        except libvirt.libvirtError as ex:
            log(self, LOG_LEVEL_ERROR, "exception raised is : {0}".format(ex))
            reply = iq.buildReply('error')
            payload = xmpp.Node("error", attrs={"code": str(ex.get_error_code())})
            payload.addData(str(ex))
            reply.setQueryPayload([payload])
        except Exception as ex:
            log(self, LOG_LEVEL_ERROR, "exception raised is : {0}".format(ex))
            reply = iq.buildReply('error')
            reply.setQueryPayload([str(ex)])
        return reply
    
    
    
    
    ######################################################################################################
    ### XMPP Processing
    ######################################################################################################
    
    def __process_iq_trinity_control(self, conn, iq):
        """
        Invoked when new trinity:vm:control IQ is received. 
        
        it understands IQ of type:
            - info
            - create
            - shutdown
            - reboot
            - suspend
            - resume
        
        @type conn: xmpp.Dispatcher
        @param conn: ths instance of the current connection that send the message
        @type iq: xmpp.Protocol.Iq
        @param iq: the received IQ
        """
        log(self, LOG_LEVEL_DEBUG, "Control IQ received from {0} with type {1}".format(iq.getFrom(), iq.getType()))
        
        #if not self.is_jid_subscribed(xmpp.JID(iq.getFrom())):
        #    return
            #reply = iq.buildReply('error')
            #response = xmpp.Node(tag="subscription-required")
            #reply.setQueryPayload([response])
            #raise xmpp.protocol.NodeProcessed
        
        
        iqType = iq.getTag("query").getAttr("type");
        
        if iqType == "info":
            reply = self.__info(iq)
            conn.send(reply)
            raise xmpp.protocol.NodeProcessed
            
        if iqType == "create":
            reply = self.__create(iq)
            conn.send(reply)
            raise xmpp.protocol.NodeProcessed
            
        if iqType == "shutdown":
            reply = self.__shutdown(iq)
            conn.send(reply)
            raise xmpp.protocol.NodeProcessed
            
        if iqType == "reboot":
            reply = self.__reboot(iq)
            conn.send(reply)
            raise xmpp.protocol.NodeProcessed
            
        if iqType == "suspend":
            reply = self.__suspend(iq)
            conn.send(reply)
            raise xmpp.protocol.NodeProcessed
            
        if iqType == "resume":
            reply = self.__resume(iq)
            conn.send(reply)
            raise xmpp.protocol.NodeProcessed
            
        if iqType == "vncdisplay":
            reply = self.__vncdisplay(iq)
            conn.send(reply)
            raise xmpp.protocol.NodeProcessed
            
        if iqType == "xmldesc":
            reply = self.__xml_description(iq)
            conn.send(reply)
            raise xmpp.protocol.NodeProcessed
            
        if iqType == "networkstats":
            reply = self.__networkstats(iq)
            conn.send(reply)
            raise xmpp.protocol.NodeProcessed
    
    
    def __process_iq_trinity_definition(self, conn, iq):
        """
        Invoked when new trinity:define IQ is received.
        
        it understands IQ of type:
            - define (the domain xml must be sent as payload of IQ, and the uuid *MUST*, be the same as the JID of the client)
            - undefine (undefine a virtual machine domain)
        
        @type conn: xmpp.Dispatcher
        @param conn: ths instance of the current connection that send the message
        @type iq: xmpp.Protocol.Iq
        @param iq: the received IQ
        """
        log(self, LOG_LEVEL_DEBUG, "Definition IQ received from {0} with type {1}".format(iq.getFrom(), iq.getType()))
        
        iqType = iq.getTag("query").getAttr("type");
        
        if iqType == "define":
            reply = self.__define(iq)
            conn.send(reply)
            raise xmpp.protocol.NodeProcessed
        
        if iqType == "undefine":
            reply = self.__undefine(iq)
            conn.send(reply)
            raise xmpp.protocol.NodeProcessed        
    
    

