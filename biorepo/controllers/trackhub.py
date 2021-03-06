# -*- coding: utf-8 -*-
"""Trackhubs Controller"""
from biorepo.lib.base import BaseController
from biorepo import handler
from repoze.what.predicates import has_any_permission
import os
from tg import request, session, expose, url, flash
from tg import app_globals as gl
from tg.decorators import with_trailing_slash
from tg.controllers import redirect
from biorepo.lib import util
from biorepo.lib.constant import trackhubs_path
from biorepo.widgets.datagrids import TrackhubGrid
import socket
import shutil
import tw2.forms as twf
from biorepo.widgets.forms import build_form_edit_th

__all__ = ['TrackhubController']


class Trackhub:
    def __init__(self, name, url_th):
        self.name = name
        self.url_th = url_th


class TrackhubController(BaseController):
    allow_only = has_any_permission(gl.perm_admin, gl.perm_user)

    @with_trailing_slash
    @expose('biorepo.templates.list_no_new')
    def index(self, *args, **kw):
        user = handler.user.get_user_in_session(request)
        user_lab = session.get("current_lab", None)
        mail = user.email
        mail_tmp = mail.split("@")
        mail_final = mail_tmp[0] + "AT" + mail_tmp[1]
        user_TH_path = trackhubs_path() + "/" + user_lab + "/" + mail_final
        trackhubs = []
        if os.path.exists(user_TH_path):
            list_trackhubs = os.listdir(user_TH_path)
            for t in list_trackhubs:
                th_path = user_TH_path + "/" + t
                #the only one directory into at this th level is named by the assembly used for it
                for i in os.listdir(th_path):
                    path_to_test = th_path + "/" + i
                    if os.path.isdir(path_to_test):
                        assembly = i
                if not assembly:
                    break
                else:
                    #hub_url = th_path + "/hub.txt"
                    hostname = socket.gethostname().lower()
                    #because of aliasing
                    if hostname == "ptbbsrv2.epfl.ch":
                        hostname = "biorepo.epfl.ch"
                    hub_url = "http://" + hostname + url("/trackHubs/") + user_lab + "/" + mail_final + "/" + t + "/hub.txt"
                    th = Trackhub(t, 'http://genome.ucsc.edu/cgi-bin/hgTracks?hubUrl=' + hub_url + "&db=" + assembly)
                    trackhubs.append(th)

        all_trackhubs = [util.to_datagrid(TrackhubGrid(), trackhubs, " UCSC's Trackhub(s)", len(trackhubs) > 0)]

        return dict(page='trackhubs', model=trackhubs, items=all_trackhubs, value=kw)

    @expose('biorepo.templates.edit_trackhub')
    def edit(self, *args, **kw):
        th_name = str(args[0])
        session["th_name"] = th_name
        session.save()
        user = handler.user.get_user_in_session(request)
        user_lab = session.get("current_lab", None)
        mail_path = str(user._email).lower().replace('@','AT')

        if user_lab is None:
            flash("Problem detected with your lab in session. Contact your administrator please", 'error')
            raise redirect('/trackhubs')

        complementary_path = str(user_lab) + "/" + mail_path + "/" + th_name + "/"
        th_path = trackhubs_path() + "/" + complementary_path
        genome_path = th_path + "genomes.txt"
        if os.path.exists(genome_path):
            #get the final path
            with open (genome_path, 'r') as gen:
                l = gen.readline()
                while l!='':
                    if l.startswith("trackDb"):
                        trackdb_path = l.split('trackDb')[1].strip()
                    l = gen.readline()
            final_path = th_path + trackdb_path + "trackDb.txt"
            with open(final_path, 'r') as final:
                l = final.readline()
                dic_colors = {}
                cpt = 0
                while l!='':
                    if l.startswith("\ttrack"):
                        track = l.split("\ttrack")[1].strip()
                        dic_colors[cpt] = track
                        cpt+=1
                    elif l.startswith("\tcolor"):
                        color = l.split("\tcolor")[1].strip()
                        dic_colors[cpt] = color
                        cpt += 1
                    l = final.readline()

            t_length = len(dic_colors.keys())
            edit_form = build_form_edit_th(t_length)(action=url('/trackhubs/post_edit')).req()
            for k, v in dic_colors.items():
                #even --> track
                if (k % 2 == 0):
                    edit_form.child.children[k].value = v
                #odd --> color
                else:
                    edit_form.child.children[k].value = v

            return dict(page='trackhubs', widget=edit_form, value=kw)
        else:
            flash("Your trackhub is not accessible right now. Hardware problem on /data. Sorry for this inconvenient, retry in a fiew moment please.", 'error')
            raise redirect('/trackhubs')

    @expose()
    def post_edit(self, *args, **kw):
        dic_colors = {}
        th_name = session["th_name"]
        user = handler.user.get_user_in_session(request)
        user_lab = session.get("current_lab", None)
        mail_path = str(user._email).lower().replace('@','AT')
        for key in kw.keys():
            if key.startswith('Color_Track_'):
                key_id = key.replace('Color_Track_','')
                dic_colors[int(key_id)] = kw[key] + "\n\n"

        #paths...
        complementary_path = str(user_lab) + "/" + mail_path + "/" + th_name + "/"
        th_path = trackhubs_path() + "/" + complementary_path
        genome_path = th_path + "genomes.txt"
        if os.path.exists(genome_path):
            #get the final path
            with open (genome_path, 'r') as gen:
                l = gen.readline()
                while l!='':
                    if l.startswith("trackDb"):
                        trackdb_path = l.split('trackDb')[1].strip()
                    l = gen.readline()
            source_path = th_path + trackdb_path + "trackDb.txt"
            final_path_tmp = th_path + trackdb_path + "trackDb_tmp.txt"
            with open (source_path, 'r') as source:
                with open(final_path_tmp, 'a') as destination:
                    l = source.readline()
                    color_cpt = 0
                    while l!='':
                        if l.startswith("\tcolor "):
                            color_cpt += 1
                            destination.write("\tcolor " + dic_colors[color_cpt])
                        else:
                            destination.write(l)
                        l = source.readline()

            #remove old file
            os.remove(source_path)
            #rename new one
            os.rename(final_path_tmp, source_path)
            flash("Trackhub edited !")
            raise redirect("/trackhubs")
        else:
            flash("Your trackhub is not accessible right now. Hardware problem on /data. Sorry for this inconvenient, retry in a fiew moment please.", 'error')
            raise redirect('/trackhubs')


    @expose()
    def delete(self, *args, **kw):
        th_name = str(args[0])
        user = handler.user.get_user_in_session(request)
        user_lab = session.get("current_lab", None)
        mail = user.email
        mail_tmp = mail.split("@")
        mail_final = mail_tmp[0] + "AT" + mail_tmp[1]
        user_path = trackhubs_path() + "/" + user_lab + "/" + mail_final
        th_path = user_path + "/" + th_name
        try:
            shutil.rmtree(th_path)
            flash("Your trackhub " + th_name + " was deleted.")
        except:
            flash("Error : your trackhub was not deleted. Contact the administrator please.", 'error')
        raise redirect(url('/trackhubs'))
