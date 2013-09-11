# -*- coding: utf-8 -*-
"""Public Controller"""
from biorepo.lib.base import BaseController
from tg import expose, flash, redirect, response, url
from biorepo.model import DBSession, Files_up, Measurements
from biorepo.lib.constant import dico_mimetypes
import os
from biorepo.lib.util import check_boolean

__all__ = ['PublicController']


class PublicController(BaseController):

    @expose()
    def public_link(self, sha1, *args, **kw):
        f = DBSession.query(Files_up).filter(Files_up.sha1 == sha1).first()
        path_fu = f.path + "/" + f.sha1
        extension = f.extension
        filename = f.filename
        file_size = os.path.getsize(path_fu)
        if dico_mimetypes.has_key(extension):
            response.content_type = dico_mimetypes[extension]
        else:
            response.content_type = 'text/plain'
        response.headers['X-Sendfile'] = path_fu
        response.headers['Content-Disposition'] = 'attachement; filename=%s' % (filename)
        response.content_length = '%s' % (file_size)
        return None

    @expose()
    def UCSC_link(self, sha1, meas_id, *args, **kw):
        #URL example
        #http://genome.ucsc.edu/cgi-bin/hgTracks?org=mouse&hgt.customText=http://yoururl.com/tracks.txt&db=mm9&position=chr4:107816815-107817581
        assemblies_Org = {'mm8': 'mouse', 'mm9': 'mouse', 'saccer2': 'yeast'}
        meas = DBSession.query(Measurements).filter(Measurements.id == meas_id).first()
        list_a_values = []
        #get the dynamic values
        for val in meas.a_values:
            list_a_values.append(val.id)
        #check if "assembly" is a dynamic key for this measurement
        for a in meas.attributs:
            if a.key == "assembly":
                #get all the values recorded for this key
                list_assemblies = a.values
                assembly = ''
                for v in list_assemblies:
                    #check if the Attributs_values object is linked to this measurement
                    if v.id in list_a_values:
                        assembly = v.value
                if assembly == '':
                    flash("Sorry but you have to set an assembly to this measurement", "error")
                    raise redirect("/search")

                elif assembly.lower() in assemblies_Org.keys():
                    org = assemblies_Org[assembly]
                    raise redirect('http://genome.ucsc.edu/cgi-bin/hgTracks?org=' + org + "&hgt.customText=" + url("/public/public_link?sha1=") + sha1 + "&db=" + assembly)
                else:
                    flash("Sorry, the assembly is not known by BioRepo. Contact your administrator please.", "error")
                    raise redirect("/search")
            else:
                flash("oups error", "error")
                raise redirect("/search")
