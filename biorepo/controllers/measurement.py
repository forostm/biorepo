# -*- coding: utf-8 -*-
"""Measurement Controller"""
from tgext.crud import CrudRestController
from biorepo.lib.base import BaseController
import tg
from tg import expose, flash, request, session
from repoze.what.predicates import has_any_permission
from tg.controllers import redirect
from biorepo.widgets.forms import build_form, NewTrackHub
from biorepo.widgets.datagrids import MeasGrid
from biorepo.model import DBSession, Measurements, User, Samples, Projects, Files_up, Attributs, Attributs_values, Labs
from tg import app_globals as gl
from tg.decorators import with_trailing_slash
from biorepo import handler
from biorepo.lib import util
from tg import url, response
import zipfile
from biorepo.lib.util import MyZipFile
import tempfile

import os
import re
from pkg_resources import resource_filename
from biorepo.lib.constant import path_processed, path_raw, path_tmp, dico_mimetypes, list_types_extern, HTS_path_data, HTS_path_archive, hts_bs_path, archives_path
from biorepo.lib.util import sha1_generation_controller, create_meas, manage_fu, manage_fu_from_HTS, isAdmin, check_boolean, display_file_size, print_traceback
import cgi
from sqlalchemy import and_, or_
import socket
from random import randint
import uuid
import json
import urllib2
from tgext.asyncjob import asyncjob_perform
from email.mime.text import MIMEText
from subprocess import Popen, PIPE

import datetime
date_format = "%d/%m/%Y"

#FOR THE DATA UPLOAD
public_dirname = os.path.join(os.path.abspath(resource_filename('biorepo', 'public')))
#data_dirname = os.path.join(public_dirname, 'data')


__all__ = ['MeasurementController']


class MeasurementController(BaseController):
    allow_only = has_any_permission(gl.perm_admin, gl.perm_user)

    @with_trailing_slash
    @expose('biorepo.templates.list')
    @expose('json')
    def index(self, *args, **kw):
        user = handler.user.get_user_in_session(request)
        admins = tg.config.get('admin.mails')
        mail = user.email
        user_lab = session.get("current_lab", None)
        if user_lab and mail not in admins:
            lab = DBSession.query(Labs).filter(Labs.name == user_lab).first()
            attributs = DBSession.query(Attributs).filter(and_(Attributs.lab_id == lab.id, Attributs.deprecated == False)).all()
            measurements = []
            for a in attributs:
                for m in a.measurements:
                    if m not in measurements and m.user_id == user.id:
                        measurements.append(m)
        elif mail in admins:
            lab = DBSession.query(Labs).filter(Labs.name == user_lab).first()
            attributs = DBSession.query(Attributs).filter(and_(Attributs.lab_id == lab.id, Attributs.deprecated == False)).all()
            measurements = []
            for a in attributs:
                for m in a.measurements:
                    if m not in measurements:
                        measurements.append(m)
            #too long to display
            #measurements = DBSession.query(Measurements).all()

        all_measurements = [util.to_datagrid(MeasGrid(), measurements, "Measurements Table", len(measurements) > 0)]

        return dict(page='measurements', model='measurement', form_title="new measurement", items=all_measurements,
                    value=kw)

    #BROWSER VERSION
    @expose('biorepo.templates.new_meas')
    def new(self, *args, **kw):
        user = handler.user.get_user_in_session(request)
        user_lab = session.get('current_lab', None)
        samples = []
        if user_lab is not None:
            lab = DBSession.query(Labs).filter(Labs.name == user_lab).first()
            attributs = DBSession.query(Attributs).filter(and_(Attributs.lab_id == lab.id, Attributs.deprecated == False)).all()
            projects = [p.id for p in user.projects if p in lab.projects]
            for a in attributs:
                for s in a.samples:
                    if s not in samples and s.project_id in projects:
                        samples.append(s)

        new_form = build_form("new", "meas", None)(action=url('/measurements/post')).req()
        new_form.child.children[3].options = [(sample.id, '%s' % (sample.name)) for sample in samples]
        return dict(page='measurements', widget=new_form)

    @expose('biorepo.templates.new_meas')
    def new_with_parents(self, *args, **kw):
        user = handler.user.get_user_in_session(request)
        user_lab = session.get('current_lab', None)
        samples = []
        if user_lab is not None:
            lab = DBSession.query(Labs).filter(Labs.name == user_lab).first()
            attributs = DBSession.query(Attributs).filter(and_(Attributs.lab_id == lab.id, Attributs.deprecated == False)).all()
            projects = [p.id for p in user.projects if p in lab.projects]
            for a in attributs:
                for s in a.samples:
                    if s not in samples and s.project_id in projects:
                        samples.append(s)

        #make_son (button "upload as child of..." in /search)
        list_meas = []
        list_parents = kw.get('parents', None)
        if list_parents == "null":
            flash("Select one or several parent(s) measurement(s) please", 'error')
            raise redirect(url('/search'))
        if list_parents is not None:
            listID = list_parents
            try:
                for i in listID.split(','):
                    measu = DBSession.query(Measurements).filter(Measurements.id == i).all()
                    for j in measu:
                        list_meas.append(j)
            except:
                for i in listID:
                    measu = DBSession.query(Measurements).filter(Measurements.id == i).all()
                    for j in measu:
                        list_meas.append(j)

        parents = list_meas
        kw['parents'] = parents

        new_form = build_form("new_parents", "meas", None)(action=url('/measurements/post')).req()
        new_form.child.children[3].options = [(sample.id, '%s' % (sample.name)) for sample in samples]
        new_form.child.children[6].options = [(m.id, '%s (%s)' % (m.name, m.id), {'selected': True}) for m in parents]
        return dict(page='measurements', widget=new_form)

    @expose('biorepo.templates.edit_meas')
    def edit(self, *args, **kw):
        user = handler.user.get_user_in_session(request)
        measurement = DBSession.query(Measurements).filter(Measurements.id == args[0]).first()
        admin = isAdmin(user)
        if admin:
            samples = DBSession.query(Samples).all()
        else:
            user_lab = session.get('current_lab', None)
            samples = []
            if user_lab is not None:
                lab = DBSession.query(Labs).filter(Labs.name == user_lab).first()
                attributs = DBSession.query(Attributs).filter(and_(Attributs.lab_id == lab.id, Attributs.deprecated == False)).all()
                projects = [p.id for p in user.projects if p in lab.projects]
                for a in attributs:
                    for s in a.samples:
                        if s not in samples and s.project_id in projects:
                            samples.append(s)
        fus = measurement.fus
        for i in fus:
            fu = i
        kw['user'] = user.id
        kw['description'] = measurement.description
        if measurement.get_userid == user.id or admin:
            #samples selected
            list_unselected = [s for s in samples if s not in measurement.samples]
            samples_selected = [(sample.id, '%s' % (sample.name)) for sample in list_unselected] + [(sample.id, '%s' % (sample.name), {'selected': True}) for sample in measurement.samples]
            #parents selected
            edit_form = build_form("edit", "meas", measurement.id)(action=url('/measurements/post_edit')).req()
            edit_form.child.children[0].value = measurement.id
            edit_form.child.children[1].value = measurement.name
            edit_form.child.children[2].value = measurement.description
            edit_form.child.children[3].options = samples_selected
            edit_form.child.children[4].value = measurement.status_type
            edit_form.child.children[5].value = measurement.type
            parents = measurement.parents
            edit_form.child.children[6].options = [(m.id, '%s (%s)' % (m.name, m.id), {'selected': True}) for m in parents]
            try:
                edit_form.child.children[7].value = fu.filename
                edit_form.child.children[8].value = fu.url_path
            except:
                edit_form.child.children[7].value = "NO FILE"
                if measurement.description is not None:
                    try:
                        url_tmp = (measurement.description).split('URL added : ')
                        str(url_tmp[1])
                    except:
                        url_tmp = (measurement.description).split('URL PROVIDED : ')
                try:
                    if len(url_tmp) > 2:
                        n = len(url_tmp) - 1
                        url_tmp2 = url_tmp[n].split('\n')
                    else:
                        url_tmp2 = url_tmp[1].split('\n')
                    url_path = url_tmp2[0]
                    edit_form.child.children[8].value = url_path
                except:
                    edit_form.child.children[8].value = None

            return dict(page='measurements', widget=edit_form, value=kw)
        else:
            flash("It is not your data -> you are not allowed to edit it", 'error')
            raise redirect(url('/measurements'))

    #COMMAND LINE VERSION
    @expose('json')
    def create(self, *args, **kw):
        user = handler.user.get_user_in_session(request)
        lab = kw.get("lab", None)
        if lab is None:
            return {"ERROR": "We need to know the lab of the user..."}

        tmp_dirname = os.path.join(public_dirname, path_tmp(lab))
        local_path = kw.get('path', None)
        if local_path is not None and local_path.endswith("/"):
            return {"ERROR": "your file is not in the archive or you made a mistake with its name"}
        url_path = kw.get('url_path', None)
        url_bool_tmp = kw.get('url_up', False)
        url_bool = check_boolean(url_bool_tmp)
        vitalit_path = kw.get("vitalit_path", None)
        if vitalit_path == '':
            vitalit_path = None
        #Upload impossible from Geneva and Lausanne LIMS, url_bool must be False
        if url_path is not None and (re.search(r'uhts-lgtf', url_path) or re.search(r'uhts-gva', url_path)) and url_bool:
            url_bool = False

        #testing the sha1 and generate it with other stuff of interest
        if vitalit_path is None:
            sha1, filename, tmp_path = sha1_generation_controller(local_path, url_path, url_bool, tmp_dirname)
        else:
            sha1, filename, tmp_path = sha1_generation_controller(vitalit_path, url_path, url_bool, tmp_dirname)

        #new measurement management
        new_meas = Measurements()
        dest_raw = path_raw(lab) + User.get_path_perso(user)
        dest_processed = path_processed(lab) + User.get_path_perso(user)

        #correction for the kw from the multi_upload.py
        status_type = kw.get('status_type', True)
        if status_type == "True":
            status_type = True
        elif status_type == "False":
            status_type = False

        type_ = kw.get('type', True)
        if type_ == "True":
            type_ = True
        elif type_ == "False":
            type_ = False

        meas = create_meas(user, new_meas, kw.get('name', None), kw.get('description', None), status_type,
                type_, kw.get('samples', None), kw.get('parent_id', None), dest_raw, dest_processed)

        #print serveur
        print meas, "building measurement with wget"
        #file upload management
        existing_fu = DBSession.query(Files_up).filter(Files_up.sha1 == sha1).first()
        #nb : tmp_path is None when user gave just an url and didn't want to upload the file into BioRepo
        if tmp_path is not None:
            if vitalit_path is None:
                fu_ = manage_fu(existing_fu, meas, public_dirname, filename, sha1, local_path, url_path, url_bool, dest_raw, dest_processed, tmp_path, lab)
            else:
                fu_ = manage_fu(existing_fu, meas, public_dirname, filename, sha1, vitalit_path, url_path, url_bool, dest_raw, dest_processed, tmp_path, lab)
            if url_path is not None:
                if meas.description is None:
                    meas.description = "Attached file uploaded from : " + url_path
                else:
                    meas.description = meas.description + "\nAttached file uploaded from : " + url_path
            else:
                if meas.description is None:
                    meas.description = "Attached file : " + filename
                else:
                    meas.description = meas.description + "\nAttached file : " + filename
        else:
            fu_ = None
            if meas.description is None:
                meas.description = "URL PROVIDED : " + url_path
            else:
                meas.description = meas.description + "\nURL PROVIDED : " + url_path
            DBSession.add(meas)
            DBSession.flush()

        #dynamicity
        list_static = ['upload', 'url_path', 'path', 'url_up', 'parents', 'name', 'description', 'user_id', 'status_type', 'type', 'samples', 'IDselected', 'lab', 'key', 'mail', 'vitalit_path', 'upload_way']
        list_dynamic = []
        labo = DBSession.query(Labs).filter(Labs.name == lab).first()
        lab_id = labo.id
        #save the attributs of the lab for final comparison
        dynamic_keys = []
        lab_attributs = DBSession.query(Attributs).filter(and_(Attributs.lab_id == lab_id, Attributs.deprecated == False, Attributs.owner == "measurement")).all()
        for i in lab_attributs:
            dynamic_keys.append(i.key)

        #check each dynamic kw
        for x in kw:
            if x not in list_static:
                list_dynamic.append(x)
                #get the attribut
                a = DBSession.query(Attributs).filter(and_(Attributs.lab_id == lab_id, Attributs.key == x, Attributs.deprecated == False, Attributs.owner == "measurement")).first()
                if a is not None:
                    #get its value(s)
                    (meas.attributs).append(a)
                    #if values of the attribute are fixed
                    if a.fixed_value == True and kw[x] is not None and kw[x] != '' and a.widget != "checkbox" and a.widget != "hiding_checkbox":
                        value = kw[x]
                        list_value = DBSession.query(Attributs_values).filter(and_(Attributs_values.attribut_id == a.id, Attributs_values.deprecated == False)).all()
                        for v in list_value:
                            #if the keyword value is in the value list, the attributs_values object is saved in the cross table
                            if (v.value).lower() == value.lower() and v not in meas.a_values:
                                (meas.a_values).append(v)
                                DBSession.flush()
                    #if values of the attribute are free
                    elif a.fixed_value == False and a.widget != "checkbox" and a.widget != "hiding_checkbox":
                        av = Attributs_values()
                        av.attribut_id = a.id
                        av.value = kw.get(x, None)
                        if av.value == '':
                            av.value = None
                        av.deprecated = False
                        DBSession.add(av)
                        DBSession.flush()
                        (meas.a_values).append(av)
                        DBSession.flush()
                    #
                    elif a.widget == "checkbox" or a.widget == "hiding_checkbox":
                        #Why 3 ? Because 3 cases max registred : True, False and None ---> so <3
                        if len(a.values) < 3:
                            av = Attributs_values()
                            av.attribut_id = a.id
                            #for True value, Attribut key and value have to be similar into the excel sheet...
                            if (kw[x]).lower() == x.lower():
                                av.value = True
                            #...and different for the False :)
                            else:
                                av.value = False
                            av.deprecated = False
                            DBSession.add(av)
                            DBSession.flush()
                            (meas.a_values).append(av)
                            DBSession.flush()
                        else:
                            if (kw[x]).lower() == x.lower():
                                for v in a.values:
                                    if check_boolean(v.value) and v.value is not None:
                                        (meas.a_values).append(v)
                            else:
                                for v in a.values:
                                    if check_boolean(v.value) == False and v.value is not None:
                                        (meas.a_values).append(v)

                            DBSession.flush()

        #to take in account the empty dynamic fields in the excel sheet
        for k in dynamic_keys:
            if k not in list_dynamic:
                print k, "--------- NOT FOUND IN MEASUREMENTS DESCRIPTION IN EXCEL SHEET"
                a = DBSession.query(Attributs).filter(and_(Attributs.lab_id == lab_id, Attributs.key == k, Attributs.deprecated == False, Attributs.owner == "measurement")).first()
                (meas.attributs).append(a)
                DBSession.flush()
        if fu_:
            return {"meas_id": meas.id, "fu_id": fu_.id, "fu_filename": fu_.filename, "fu_url": fu_.url_path}
        else:
            return {"meas_id": meas.id}

    @expose('biorepo.templates.new_meas')
    def clone(self, *args, **kw):
        #take the logged user
        user = handler.user.get_user_in_session(request)
        user_lab = session.get('current_lab', None)
        samples = []
        if user_lab is not None:
            lab = DBSession.query(Labs).filter(Labs.name == user_lab).first()
            attributs = DBSession.query(Attributs).filter(and_(Attributs.lab_id == lab.id, Attributs.deprecated == False)).all()
            projects = [p.id for p in user.projects if p in lab.projects]
            for a in attributs:
                for s in a.samples:
                    if s not in samples and s.project_id in projects:
                        samples.append(s)

        #clone measurement (button "clone it" in /search)
        to_clone = kw.get('clone', None)
        if to_clone == "null":
            flash("Select one measurement to clone please", 'error')
            raise redirect(url('/search'))
        if to_clone is not None:
            listID = to_clone
            cpt = 0
            try:
                for i in listID.split(','):
                    measu = DBSession.query(Measurements).filter(Measurements.id == i).first()
                    cpt += 1
            except:
                for i in listID:
                    measu = DBSession.query(Measurements).filter(Measurements.id == i).first()
                    cpt += 1
        if cpt > 1:
            flash("Select just one measurement please.", "error")
            raise redirect(url('/search'))

        #samples selected
        list_unselected = [s for s in samples if s not in measu.samples]
        samples_selected = [(sample.id, '%s' % (sample.name)) for sample in list_unselected] + [(sample.id, '%s' % (sample.name), {'selected': True}) for sample in measu.samples]
        new_form = build_form("clone", "meas", measu.id)(action=url('/measurements/post')).req()
        new_form.child.children[1].value = measu.name
        new_form.child.children[2].value = measu.description
        new_form.child.children[3].options = samples_selected
        new_form.child.children[4].value = measu.status_type
        new_form.child.children[5].value = measu.type
        return dict(page='measurements', widget=new_form)

    @expose('genshi:tgext.crud.templates.post')
    def post(self, *args, **kw):
        user = handler.user.get_user_in_session(request)
        lab = session.get('current_lab', None)
        if lab is None:
            flash("Sorry, something wrong happened with your lab id. Retry or contact admin.", "error")
            raise redirect('./measurements')
        #TODO recuperer la session pour l'id du lab ou le nom du lab
        tmp_dirname = os.path.join(public_dirname, path_tmp(lab))
        local_path = kw.get('upload', None)
        #if not local_path:
        if isinstance(local_path, cgi.FieldStorage) and not getattr(local_path, 'filename'):
            local_path = None
        if local_path == '':
            local_path = None
        url_path = kw.get('url_path', None)
        if url_path == '':
            url_path = None
        url_bool = kw.get('url_up', False)
        #change TW1 -> TW2 : True == on and False == None
        if url_bool == "on":
            url_bool = True
        elif url_bool is None:
            url_bool = False

        vitalit_path = kw.get("vitalit_path", None)
        if vitalit_path == '':
            vitalit_path = None

        #make_son (button "upload as child of..." in /search) #TODO juste mettre les ids
        list_meas = []
        list_parents = kw.get('parents', None)
        if list_parents is not None:
            listID = list_parents
            try:
                for i in listID.split(','):
                    measu = DBSession.query(Measurements).filter(Measurements.id == i).all()
                    for j in measu:
                        list_meas.append(i)
            except:
                for i in listID:
                    measu = DBSession.query(Measurements).filter(Measurements.id == i).all()
                    for j in measu:
                        list_meas.append(j)

        kw['parents'] = list_meas
        list_s = kw.get('samples', None)
        if list_s is not None and type(list_s) is not list:
            list_s = [list_s]

        if vitalit_path is not None and (not vitalit_path.startswith("/scratch/el/biorepo/dropbox/"
        ) and not vitalit_path.startswith("/scratch/cluster/dropbox/biorepo/")):
            flash("Sorry, your Vital-IT path must begin with '/scratch/el(or cluster)/biorepo/dropbox/'", "error")
            raise redirect('./new')
        elif local_path is None and url_path is None and vitalit_path is None:
            flash("Bad Measurement : You have to give a file or an url with it.", "error")
            raise redirect("./new")

        else:
            #testing the sha1 and generate it with other stuff of interest
            if not url_bool and local_path is None:
                sha1, filename, tmp_path = sha1_generation_controller(vitalit_path, url_path, url_bool, tmp_dirname)
            elif vitalit_path is None:
                sha1, filename, tmp_path = sha1_generation_controller(local_path, url_path, url_bool, tmp_dirname)
            else:
                flash("Sorry, you have to choose one and only one way to attach the file to the measurement", "error")
                raise redirect('./measurements')

        #new measurement management
        new_meas = Measurements()
        dest_raw = path_raw(lab) + User.get_path_perso(user)
        dest_processed = path_processed(lab) + User.get_path_perso(user)
        if kw['name'] == '' or kw['name'] is None:
            flash("Bad Measurement : You have to give a name to your measurement.", "error")
            raise redirect("./new")

        meas = create_meas(user, new_meas, kw['name'], kw['description'], kw.get('status_type', False), kw.get('type', False),
        list_s, kw['parents'], dest_raw, dest_processed)

        #file upload management
        existing_fu = DBSession.query(Files_up).filter(Files_up.sha1 == sha1).first()
        #nb : tmp_path is None when user gave just an url and didn't want to upload the file into BioRepo
        if tmp_path is not None:
            if vitalit_path is None:
                manage_fu(existing_fu, meas, public_dirname, filename, sha1, local_path, url_path, url_bool, dest_raw, dest_processed, tmp_path, lab)
            else:
                manage_fu(existing_fu, meas, public_dirname, filename, sha1, vitalit_path, url_path, url_bool, dest_raw, dest_processed, tmp_path, lab)
            if url_path is not None:
                meas.description = meas.description + "\nAttached file uploaded from : " + url_path
            else:
                meas.description = meas.description + "\nAttached file : " + filename
        else:
            meas.description = meas.description + "\nURL PROVIDED : " + url_path
            DBSession.add(meas)
            DBSession.flush()
        #dynamicity
        list_static = ['upload', 'url_path', 'url_up', 'parents', 'name', 'description', 'user_id', 'status_type', 'type', 'samples', 'IDselected', 'vitalit_path', 'upload_way']
        list_dynamic = []
        labo = DBSession.query(Labs).filter(Labs.name == lab).first()
        lab_id = labo.id

        for x in kw:
            if x not in list_static:
                list_dynamic.append(x)
                #get the attribut
                a = DBSession.query(Attributs).filter(and_(Attributs.lab_id == lab_id, Attributs.key == x, Attributs.deprecated == False, Attributs.owner == "measurement")).first()
                if a is not None:
                    #get its value(s)
                    (meas.attributs).append(a)
                    #if values of the attribute are fixed
                    if a.fixed_value == True and kw[x] is not None and kw[x] != '' and a.widget != "checkbox" and a.widget != "hiding_checkbox":
                        value = kw[x]
                        list_value = DBSession.query(Attributs_values).filter(Attributs_values.attribut_id == a.id).all()
                        for v in list_value:
                            #if the keyword value is in the value list, the attributs_values object is saved in the cross table
                            if v.value == value and v not in meas.a_values:
                                (meas.a_values).append(v)
                                DBSession.flush()
                    #if values of the attribute are free
                    elif a.fixed_value == False and a.widget != "checkbox" and a.widget != "hiding_checkbox":
                        av = Attributs_values()
                        av.attribut_id = a.id
                        av.value = kw.get(x, None)
                        av.deprecated = False
                        DBSession.add(av)
                        DBSession.flush()
                        (meas.a_values).append(av)
                        DBSession.flush()
                    #special case for checkbox because of the "on" and None value of TW2 for True and False... (Here it's True)
                    elif a.widget == "checkbox" or a.widget == "hiding_checkbox":
                        found = False
                        for v in a.values:
                            if check_boolean(v.value) and v.value is not None:
                                (meas.a_values).append(v)
                                found = True
                        if not found:
                            av = Attributs_values()
                            av.attribut_id = a.id
                            av.value = True
                            av.deprecated = False
                            DBSession.add(av)
                            DBSession.flush()
                            (meas.a_values).append(av)
                            DBSession.flush()

        #special case for checkbox because of the "on" and None value of TW2 for True and False... (Here it's False)
        dynamic_booleans = DBSession.query(Attributs).filter(and_(Attributs.lab_id == lab_id, Attributs.deprecated == False, Attributs.owner == "measurement", or_(Attributs.widget == "checkbox", Attributs.widget == "hiding_checkbox"))).all()
        if len(dynamic_booleans) > 0:
            for d in dynamic_booleans:
                if d.key not in list_dynamic:
                    if d.widget == "checkbox" or d.widget == "hiding_checkbox":
                        found = False
                        for v in d.values:
                            if not check_boolean(v.value) and v.value is not None:
                                (meas.attributs).append(d)
                                (meas.a_values).append(v)
                                found = True
                                #to avoid IntegrityError in the db
                                break
                        if not found:
                            av = Attributs_values()
                            av.attribut_id = d.id
                            av.value = False
                            av.deprecated = False
                            DBSession.add(av)
                            DBSession.flush()
                            (meas.attributs).append(d)
                            (meas.a_values).append(av)
                            DBSession.flush()

        raise redirect("./")

    @expose()
    def download(self, meas_id, *args, **kw):
        meas = DBSession.query(Measurements).filter(Measurements.id == meas_id).first()
        #check rights to dl
        att_meas = meas.attributs[0]
        meas_lab = DBSession.query(Labs).filter(Labs.id == att_meas.lab_id).first()
        meas_labname = meas_lab.name
        lab = session.get('current_lab', None)
        if lab != meas_labname:
            flash("Sorry, this file is not a file from your lab. You can't access to it.", 'error')
            raise redirect('/search')

        list_fus = meas.fus
        if list_fus == []:
            try:
                msg_tmp = (meas.description).split('URL PROVIDED')
                msg_tmp2 = msg_tmp[1].split('\n')
                msg_url = msg_tmp2[0]
                flash("Sorry, there is no file attached with this measurement. You can download it here " + msg_url, 'error')
            except:
                flash("Sorry, there is nothing (no file, no URL) attached with this measurement. Check if it is really usefull or edit/delete it please.", 'error')

            raise redirect('/search')
        #TODO manage the possibility of multi fus for one meas ---> multidownload()
        for x in list_fus:
            #if it is a HTSstation archive
            #TODO : include /data/ from HTSstation
            if x.path.startswith('/archive/epfl/bbcf/'):
                path_fu = x.path + "/" + x.filename
            #or not
            else:
                path_fu = x.path + "/" + x.sha1
            extension = x.extension
            filename = (x.filename).replace(' ', '_')
            file_size = os.path.getsize(path_fu)
            response.content_length = file_size
            if dico_mimetypes.has_key(extension):
                response.content_type = dico_mimetypes[extension]
            else:
                response.content_type = 'text/plain'
            response.headers['X-Sendfile'] = path_fu
            response.headers['Content-Disposition'] = 'attachement; filename=%s' % (filename)
            response.content_length = '%s' % (file_size)
            return None

    @expose()
    def post_edit(self, *args, **kw):
        id_meas = kw['IDselected']
        if kw['name'] == '' or kw['name'] is None:
            flash("Bad Measurement : You have to give a name to your measurement.", "error")
            raise redirect("./edit/" + id_meas)
        measurement = DBSession.query(Measurements).filter(Measurements.id == id_meas).first()
        measurement.name = kw['name']
        measurement.description = kw['description']
        status_type_tmp = kw.get("status_type", False)
        measurement.status_type = check_boolean(status_type_tmp)
        type_tmp = kw.get("type", False)
        measurement.type = check_boolean(type_tmp)
        samples = kw.get('samples', None)
        list_samples = []
        if samples is not None:
            if type(samples) is list:
                for s in samples:
                    sample = DBSession.query(Samples).filter(Samples.id == s).first()
                    list_samples.append(sample)
            else:
                sample = DBSession.query(Samples).filter(Samples.id == samples).first()
                list_samples.append(sample)
        else:
            list_samples = []
        measurement.samples = list_samples

        now = str((datetime.datetime.now()).strftime(date_format))
        if kw['url_path']:
            if measurement.fus:
                fu = measurement.fus
                for f in fu:
                    if kw['url_path'] != f.url_path:
                        measurement.description = measurement.description + "\nEdited " + now + " - new URL : " + kw['url_path']
                        f.url_path = kw['url_path']
            else:
                url_tmp = (measurement.description).split('URL PROVIDED : ')
                try:
                    url_tmp2 = url_tmp[1].split('\n')
                    url_path = url_tmp2[0]
                except:
                    url_path = ''
                if kw['url_path'].strip() != url_path.strip():
                    measurement.description = measurement.description + "\nEdited " + now + " URL added : " + kw['url_path']
                else:
                    measurement.description = measurement.description + "\nEdited " + now

        #DYNAMICITY
        list_static = ['project', 'name', 'type', 'protocole', 'IDselected', 'measurements']
        list_attributs = []
        list_a_values = measurement.a_values
        for a in measurement.attributs:
            if a.deprecated == False:
                list_attributs.append(a)

        for x in kw:
            if x not in list_static:
                for a in list_attributs:
                    if x == a.key:
                        object_2_delete = None
                        #search if the field was edited
                        for v in list_a_values:
                            if v.attribut_id == a.id and v.value != kw[x] and a.widget != "multipleselectfield" and a.widget != "hiding_multipleselectfield":
                                object_2_delete = v
                        if a.widget == "textfield" or a.widget == "hiding_textfield" or a.widget == "textarea" or a.widget == "hiding_textarea":
                            if object_2_delete:
                                object_2_delete.value = kw[x]
                        elif a.widget == "checkbox" or a.widget == "hiding_checkbox":
                            if len(a.values) < 3:
                                for old_v in a.values:
                                    if old_v.value is not None and old_v.value != '':
                                        list_a_values.remove(old_v)
                                av = Attributs_values()
                                av.attribut_id = a.id
                                av.value = True
                                av.deprecated = False
                                DBSession.add(av)
                                list_a_values.append(av)
                                DBSession.flush()

                            elif len(a.values) == 3:
                                if object_2_delete:
                                    list_a_values.remove(object_2_delete)
                                    v = object_2_delete.value
                                    for val in a.values:
                                        val_to_avoid = [None, ""]
                                        if v not in val_to_avoid:
                                            val_to_avoid.append(v)
                                        if val.value not in val_to_avoid:
                                            list_a_values.append(val)
                                            DBSession.flush()
                            else:
                                print "--- BOOLEAN ERROR ---"
                                print "boolean with more than 2 values"
                                print a.id, " attributs id"
                                raise

                        elif a.widget == "singleselectfield" or a.widget == "hiding_singleselectfield":
                            #edition : delete the connexion to the older a_value, make the connexion between the new a_value and the measurement
                            if object_2_delete:
                                list_a_values.remove(object_2_delete)
                                list_possible = a.values
                                for p in list_possible:
                                    if p.value == kw[x]:
                                        list_a_values.append(p)
                            #if the value was "None", just add the new value edited
                            elif object_2_delete is None:
                                list_possible = a.values
                                for p in list_possible:
                                    if p.value == kw[x]:
                                        list_a_values.append(p)

                        elif a.widget == "multipleselectfield" or a.widget == "hiding_multipleselectfield":
                            #!!! NOT TESTED !!!
                            list_objects_2_delete = []
                            for v in list_a_values:
                                #warning : types of i and v.value have to be similar...
                                for i in kw[x]:
                                    if v.attribut_id == a.id and v.value != i:
                                        list_objects_2_delete.append(v)
                                    if len(list_objects_2_delete) > 0:
                                        for v in list_objects_2_delete:
                                            list_a_values.remove(v)

                                        if a.fixed_value == True:
                                            to_add = DBSession.query(Attributs_values).filter(and_(Attributs_values.value == i), Attributs_values.attribut_id == a.id).first()
                                            list_a_values.append(to_add)
                                        else:
                                            #multiple selected field can't be not a fixed value.
                                            print "something wrong happenned - illogical - controller measurement post_edit()"
                                            pass
        #special case for checkbox because of the "on" and None value of TW2 for True and False... (Here it's False)
        lab = session.get('current_lab', None)
        labo = DBSession.query(Labs).filter(Labs.name == lab).first()
        lab_id = labo.id
        dynamic_booleans = DBSession.query(Attributs).filter(and_(Attributs.lab_id == lab_id, Attributs.deprecated == False, Attributs.owner == "measurement", or_(Attributs.widget == "checkbox", Attributs.widget == "hiding_checkbox"))).all()

        if len(dynamic_booleans) > 0:
            for b in dynamic_booleans:
                if b.key not in kw:
                    list_value = b.values
                    #2 cases possibles
                    #1 : values are None and (True or False)
                    if len(list_value) == 2:
                        for v in list_value:
                            #1.1 : None and True
                            val = check_boolean(v.value)
                            if val == True:
                                list_a_values.remove(v)
                                av = Attributs_values()
                                av.attribut_id = b.id
                                av.value = False
                                av.deprecated = False
                                DBSession.add(av)
                                list_a_values.append(av)
                                DBSession.flush()
                                break
                            #1.2 : None and False
                            elif val == False:
                                #because nothing was edited for the field
                                pass
                    #2 : values are None, True and False
                    elif len(list_value) == 3:
                        for v in list_value:
                            if v.value is not None:
                                val = check_boolean(v.value)
                            else:
                                val = None
                            if val == True:
                                try:
                                    list_a_values.remove(v)
                                except:
                                    pass
                            elif val == False:
                                list_a_values.append(v)

        flash("Measurement edited !")
        raise redirect("./")

    @expose()
    def delete(self, *args, **kw):
        user = handler.user.get_user_in_session(request)
        measurement = DBSession.query(Measurements).filter(Measurements.id == args[0]).first()
        list_fus = measurement.fus
        admin = isAdmin(user)

        if measurement.user_id == user.id or admin:
            try:
                flash("Your measurement " + str(measurement.name) + " has been deleted with success")
            except:
                flash("Your measurement " + (measurement.name) + " has been deleted with success")
            for f in list_fus:
                #delete the file on the server only if it is not used by anyone else anymore
                if len(f.measurements) == 1 and not (f.path).startswith(HTS_path_data()) and not (f.path).startswith(HTS_path_archive()):
                    path_fu = f.path + "/" + f.sha1
                    mail = user._email
                    mail_tmp = mail.split('@')
                    path_mail = "AT".join(mail_tmp)
                    path_symlink = f.path + "/" + path_mail + "/" + f.sha1
                    DBSession.delete(f)
                    if admin:
                        user_id = measurement.user_id
                        owner = DBSession.query(User).filter(User.id == user_id).first()
                        mail_owner = owner._email
                        mail_owner_tmp = mail_owner.split('@')
                        path_mail_owner = "AT".join(mail_owner_tmp)
                        path_symlink = f.path + "/" + path_mail_owner + "/" + f.sha1
                    else:
                        path_symlink = f.path + "/" + path_mail + "/" + f.sha1
                    try:
                        os.remove(path_symlink)
                    except:
                        print "---- path_symlink deleted yet ----"
                        pass
                    os.remove(path_fu)
                elif (f.path).startswith(HTS_path_data()) or (f.path).startswith(HTS_path_archive()):
                    DBSession.delete(f)
                    #TODO send back something to hts to notify that it's not into biorepo anymore

            DBSession.delete(measurement)
            DBSession.flush()
            raise redirect("/measurements")
        else:
            flash("It is not your data -> you are not allowed to delete it", 'error')
            raise redirect(url('/measurements'))

    @expose('json')
    def info_display(self, meas_id):
        meas = DBSession.query(Measurements).filter(Measurements.id == meas_id).first()
        if meas:
            name = meas.name
            meas_descr = meas.description
            list_fus = meas.fus
            list_parents = meas.parents
            par = ""
            #the measurement get a file attached to and is generated from other(s)
            if len(list_fus) > 0 and len(list_parents) > 0:
                for f in list_fus:
                    ext = f.extension
                    filename = f.filename
                    path_fu = f.path + "/" + f.sha1
                    try:
                        file_size = os.path.getsize(path_fu)
                    except:
                        path_fu = f.path + "/" + filename
                        file_size = os.path.getsize(path_fu)
                    final_size = display_file_size(file_size)
                for p in list_parents:
                    par = par + p.name + " (id:" + str(p.id) + ")" + " | "
                #delete the last " | "
                par = par[:-3]
                #display the bam or the bam.bai related... or not :)
                if ext.lower() == "bam":
                    bai_name = filename + ".bai"
                    bai_obj = DBSession.query(Files_up).filter(Files_up.filename == bai_name).first()
                    if bai_obj is None:
                        list_meas = []
                    else:
                        list_meas = bai_obj.measurements
                    for m in list_meas:
                        lab_name = session.get("current_lab")
                        lab = DBSession.query(Labs).filter(Labs.name == lab_name).first()
                        list_meas_owners = DBSession.query(User).filter(User.id == m.user_id).all()
                        for u in list_meas_owners:
                            if lab in u.labs:
                                bai_m_id = m.id
                                return {'Measurement': name + " (id:" + meas_id + ")", 'Description': meas_descr, 'Extension': ext, 'Filename': filename, 'From': par, 'Size': final_size, 'bai measurement id': bai_m_id}
                    #if .bam.bai is not found
                    return {'Measurement': name + " (id:" + meas_id + ")", 'Description': meas_descr, 'Extension': ext, 'Filename': filename, 'From': par, 'Size': final_size, 'bai measurement id': ' NOT FOUND IN BioRepo db'}
                elif ext.lower() == "bam.bai" or ext.lower() == "bai":
                    bam_name = filename[:-4]
                    bam_obj = DBSession.query(Files_up).filter(Files_up.filename == bam_name).first()
                    if bam_obj is None:
                        list_meas = []
                    else:
                        list_meas = bam_obj.measurements
                    for m in list_meas:
                        lab_name = session.get("current_lab")
                        lab = DBSession.query(Labs).filter(Labs.name == lab_name).first()
                        list_meas_owners = DBSession.query(User).filter(User.id == m.user_id).all()
                        for u in list_meas_owners:
                            if lab in u.labs:
                                bam_m_id = m.id
                            return {'Measurement': name + " (id:" + meas_id + ")", 'Description': meas_descr, 'Extension': ext, 'Filename': filename, 'From': par, 'Size': final_size, 'bam measurement id ': bam_m_id}
                    #if bam is not found
                    return {'Measurement': name + " (id:" + meas_id + ")", 'Description': meas_descr, 'Extension': ext, 'Filename': filename, 'From': par, 'Size': final_size, 'bam measurement id': ' NOT FOUND IN BioRepo db'}
                else:
                    return {'Measurement': name + " (id:" + meas_id + ")", 'Description': meas_descr, 'Extension': ext, 'Filename': filename, 'From': par, 'Size': final_size}

            #no parent(s)
            elif len(list_fus) > 0 and len(list_parents) == 0:
                for f in list_fus:
                    ext = f.extension
                    filename = f.filename
                    path_fu = f.path + "/" + f.sha1
                    try:
                        file_size = os.path.getsize(path_fu)
                    except:
                        path_fu = f.path + "/" + filename
                        file_size = os.path.getsize(path_fu)
                    final_size = display_file_size(file_size)
                #display the bam or the bam.bai related... or not :)
                if ext.lower() == "bam":
                    bai_name = filename + ".bai"
                    bai_obj = DBSession.query(Files_up).filter(Files_up.filename == bai_name).first()
                    if bai_obj is None:
                        list_meas = []
                    else:
                        list_meas = bai_obj.measurements
                    for m in list_meas:
                        lab_name = session.get("current_lab")
                        lab = DBSession.query(Labs).filter(Labs.name == lab_name).first()
                        list_meas_owners = DBSession.query(User).filter(User.id == m.user_id).all()
                        for u in list_meas_owners:
                            if lab in u.labs:
                                bai_m_id = m.id
                                return {'Measurement': name + " (id:" + meas_id + ")", 'Description': meas_descr, 'Extension': ext, 'Filename': filename, 'Size': final_size, 'bai measurement id ': bai_m_id}
                    #if .bam.bai is not found
                    return {'Measurement': name + " (id:" + meas_id + ")", 'Description': meas_descr, 'Extension': ext, 'Filename': filename, 'Size': final_size, 'bai measurement id': ' NOT FOUND IN BioRepo db'}
                elif ext.lower() == "bam.bai" or ext.lower() == "bai":
                    bam_name = filename[:-4]
                    bam_obj = DBSession.query(Files_up).filter(Files_up.filename == bam_name).first()
                    if bam_obj is None:
                        list_meas = []
                    else:
                        list_meas = bam_obj.measurements
                    for m in list_meas:
                        lab_name = session.get("current_lab")
                        lab = DBSession.query(Labs).filter(Labs.name == lab_name).first()
                        list_meas_owners = DBSession.query(User).filter(User.id == m.user_id).all()
                        for u in list_meas_owners:
                            if lab in u.labs:
                                bam_m_id = m.id
                                return {'Measurement': name + " (id:" + meas_id + ")", 'Description': meas_descr, 'Extension': ext, 'Filename': filename, 'Size': final_size, 'bam measurement id ': bam_m_id}
                    #if bam is not found
                    return {'Measurement': name + " (id:" + meas_id + ")", 'Description': meas_descr, 'Extension': ext, 'Filename': filename, 'Size': final_size, 'bam measurement id': ' NOT FOUND IN BioRepo db'}
                else:
                    return {'Measurement': name + " (id:" + meas_id + ")", 'Description': meas_descr, 'Extension': ext, 'Filename': filename, 'Size': final_size}

            #no file attached
            elif len(list_fus) == 0 and len(list_parents) > 0:
                for p in list_parents:
                    par = par + p.name + " (id:" + str(p.id) + ")" + " | "
                #delete the last " | "
                par = par[:-3]
                return {'Measurement': name + " (id:" + meas_id + ")", 'Description': meas_descr, 'From': par}
            else:
                return {'Measurement': name + " (id:" + meas_id + ")", 'Description': meas_descr}
        else:
            return {'Error': 'Problem with this measurement, contact your administrator'}

    @expose()
    def create_from_ext_list(self, ext_list, project, sample_type, module):
        user = handler.user.get_user_in_session(request)
        lab = session.get('current_lab', None)
        labo = DBSession.query(Labs).filter(Labs.name == lab).first()
        lab_id = labo.id
        dest_raw = path_raw(lab) + User.get_path_perso(user)
        dest_processed = path_processed(lab) + User.get_path_perso(user)
        tmp_dirname = os.path.join(public_dirname, path_tmp(lab))
        dic_final = {}
        list_meas_ids_created = []
        print ext_list, "---- type of extension save from HTSstation"
        for e in ext_list:
            p_key = project.description
            #build the dico for group_id and groupe name
            url_group = "http://htsstation.epfl.ch/groups.json?key=" + str(p_key)
            response = urllib2.urlopen(url_group)
            list_groups = json.loads(response.read())
            response.close()
            dico_gid_gname = {}
            for g in list_groups:
                dico_tmp = g["group"]
                dico_gid_gname[dico_tmp["id"]] = dico_tmp["name"]
            #parse the HTSstation project
            url_htsstation = "http://htsstation.epfl.ch/jobs/" + str(p_key) + ".json"
            response = urllib2.urlopen(url_htsstation)
            hts_dico = json.loads(response.read())
            response.close()
            tmp1_hts_dico = hts_dico["job"]
            to_json = tmp1_hts_dico["results_json"]
            tmp2_hts_dico = json.loads(to_json)
            ext_dico = tmp2_hts_dico[e]
            for m in ext_dico.iterkeys():
                m_key = m
                #parser to catch the groupId and the view
                m_value = ext_dico[m]
                filename_with_ext = m_value.split("[")[0]
                tmp_1 = m_value.split("[")[1]
                tmp_2 = tmp_1.split("]")[0]
                tmp_3 = tmp_2.split(",")
                g_id = False
                admin_file = False
                for i in tmp_3:
                    if i.startswith("groupId:"):
                        g_id = True
                        group_id = i.split(":")[1]
                        group_name = dico_gid_gname[int(group_id)]
                    #exception for demultiplexing module from HTSstation
                    elif i.startswith("group:"):
                        g_id = True
                        gname_tmp = i.split(':')
                        group_name = gname_tmp[1]
                    if i.startswith("view:admin"):
                        admin_file = True
                #pass to the next file if it is an admin file...
                if admin_file:
                    pass
                #...and save the file in BioRepo if it is not.
                else:
                    if not g_id:
                        group_name = "Global results"

                    sample = DBSession.query(Samples).filter(and_(Samples.project_id == project.id, Samples.name == group_name)).first()
                    if sample is None:
                        sample = Samples()
                        sample.project_id = project.id
                        sample.name = group_name
                        for t in list_types_extern:
                            if t.lower() == sample_type.lower():
                                sample.type = t
                                break
                            else:
                                sample.type = "External_app_sample"
                        DBSession.add(sample)
                        DBSession.flush()
                        #sample dynamicity
                        labo_attributs = DBSession.query(Attributs).filter(and_(Attributs.lab_id == lab_id, Attributs.deprecated == False, Attributs.owner == "sample")).all()
                        if len(labo_attributs) > 0:
                            for a in labo_attributs:
                                sample.attributs.append(a)

                                if a.fixed_value == True and a.widget != "checkbox" and a.widget != "hiding_checkbox":
                                    DBSession.flush()
                                #if values of the attribute are free
                                elif a.fixed_value == False and a.widget != "checkbox" and a.widget != "hiding_checkbox":
                                    av = Attributs_values()
                                    av.attribut_id = a.id
                                    av.value = None
                                    av.deprecated = False
                                    DBSession.add(av)
                                    DBSession.flush()
                                    (sample.a_values).append(av)
                                    DBSession.flush()
                                elif a.widget == "checkbox" or a.widget == "hiding_checkbox":
                                    found = False
                                    for v in a.values:
                                        if not check_boolean(v.value) and v.value is not None:
                                            (sample.a_values).append(v)
                                            found = True
                                    if not found:
                                        av = Attributs_values()
                                        av.attribut_id = a.id
                                        av.value = False
                                        av.deprecated = False
                                        DBSession.add(av)
                                        DBSession.flush()
                                        (sample.a_values).append(av)
                                        DBSession.flush()

                    list_sample_id = []
                    list_sample_id.append(sample.id)

                    new_meas = Measurements()
                    meas = create_meas(user, new_meas, str(project.project_name), None, False,
                            False, list_sample_id, None, dest_raw, dest_processed)
                    #must startswith (htsstation.epfl.ch/data)
                    file_url_full = HTS_path_data() + "/data/" + str(module) + "_minilims.files/" + str(m_key)
                    file_url = "http://htsstation.epfl.ch/data/" + str(module) + "_minilims.files/" + str(m_key)
                    if not os.path.exists(file_url_full):
                        print file_url_full, " /!\ This HTSstation path does not exist ! /!\ : " + str(file_url_full)
                        dic_final["error"] = "Problem with the file path. Does not exist : " + str(file_url_full)
                        DBSession.delete(meas)
                        return dic_final

                    sha1, filename, tmp_path = sha1_generation_controller(None, file_url, True, tmp_dirname)
                    #correction
                    filename = filename_with_ext
                    #file upload management
                    existing_fu = DBSession.query(Files_up).filter(Files_up.sha1 == sha1).first()
                    try:
                        manage_fu_from_HTS(existing_fu, meas, filename, sha1, file_url_full, tmp_path)
                    except:
                        dic_final["error"] = "Problem with the file path for " + str(filename)
                        DBSession.delete(meas)
                        return dic_final

                    if meas.description is not None:
                        meas.description = meas.description + "\nAttached file uploaded from : " + str(project.project_name)
                    else:
                        meas.description = "\nAttached file uploaded from : " + m_key + " (HTSStation file key)"
                    DBSession.add(meas)
                    DBSession.flush()
                    list_meas_ids_created.append(meas.id)
                    #measurement dynamicity
                    lab_attributs = DBSession.query(Attributs).filter(and_(Attributs.lab_id == lab_id, Attributs.deprecated == False, Attributs.owner == "measurement")).all()
                    if len(lab_attributs) > 0:
                        for a in lab_attributs:
                            meas.attributs.append(a)

                            if a.fixed_value == True and a.widget != "checkbox" and a.widget != "hiding_checkbox":
                                DBSession.flush()
                            #if values of the attribute are free
                            elif a.fixed_value == False and a.widget != "checkbox" and a.widget != "hiding_checkbox":
                                av = Attributs_values()
                                av.attribut_id = a.id
                                av.value = None
                                av.deprecated = False
                                DBSession.add(av)
                                DBSession.flush()
                                (meas.a_values).append(av)
                                DBSession.flush()
                            elif a.widget == "checkbox" or a.widget == "hiding_checkbox":
                                found = False
                                for v in a.values:
                                    if not check_boolean(v.value) and v.value is not None:
                                        (meas.a_values).append(v)
                                        found = True
                                if not found:
                                    av = Attributs_values()
                                    av.attribut_id = a.id
                                    av.value = False
                                    av.deprecated = False
                                    DBSession.add(av)
                                    DBSession.flush()
                                    (meas.a_values).append(av)
                                    DBSession.flush()
        #final (out of the first "for" loop)
        dic_final["meas_id"] = list_meas_ids_created
        return dic_final

    @expose()
    def external_add(self, *args, **kw):
        '''
        used to upload a project with files/an archive/a file from another web application
        '''
        user = handler.user.get_user_in_session(request)
        user_id = user.id
        lab = session.get('current_lab', None)
        labo = DBSession.query(Labs).filter(Labs.name == lab).first()
        lab_id = labo.id
        #get the initial kws from the external app which
        backup_dico = session.get("backup_kw")
        file_path = backup_dico["file_path"]
        description = backup_dico["description"]
        project_name = backup_dico["project_name"]
        sample_name = backup_dico["sample_name"]
        sample_type = backup_dico["sample_type"]
        #{sha1:(filename,tmp_path)} if HTSstation/BioScript - else : empty.
        fu_dico = {}
        #to send back to HTSstation
        list_meas_ids_created = []
        #test sha1
        tmp_dirname = os.path.join(public_dirname, path_tmp(lab))
        if file_path.startswith("http://"):
            sha1, filename, tmp_path = sha1_generation_controller(None, file_path, True, tmp_dirname)
        else:
            if "task_id" in backup_dico:
                task_id = str(backup_dico["task_id"])
                file_path_list = file_path.split(',')
                for p in file_path_list:
                    file_path = hts_bs_path() + "/" + task_id + "/" + p
                    sha1, filename, tmp_path = sha1_generation_controller(file_path, None, False, tmp_dirname)
                    fu_dico[sha1] = (filename, tmp_path)
            else:
                sha1, filename, tmp_path = sha1_generation_controller(file_path, None, False, tmp_dirname)

        #new measurement management
        new_meas = Measurements()
        dest_raw = path_raw(lab) + User.get_path_perso(user)
        dest_processed = path_processed(lab) + User.get_path_perso(user)

        #create project and sample
        project = DBSession.query(Projects).filter(and_(Projects.user_id == user_id, Projects.project_name == project_name)).first()
        if project is None or labo not in project.labs:
            project = Projects()
            project.project_name = project_name
            project.user_id = user_id
            #HTS spec
            if "project_description" in backup_dico:
                project.description = backup_dico["project_description"]
            (project.labs).append(labo)
            DBSession.add(project)
            DBSession.flush()

        sample = DBSession.query(Samples).filter(and_(Samples.project_id == project.id, Samples.name == sample_name)).first()
        if sample is None:
            sample = Samples()
            sample.project_id = project.id
            sample.name = sample_name
            for t in list_types_extern:
                if t.lower() == sample_type.lower():
                    sample.type = t
                    break
                else:
                    sample.type = "External_app_sample"
            DBSession.add(sample)
            DBSession.flush()
            #sample dynamicity
            labo_attributs = DBSession.query(Attributs).filter(and_(Attributs.lab_id == lab_id, Attributs.deprecated == False, Attributs.owner == "sample")).all()
            if len(labo_attributs) > 0:
                for a in labo_attributs:
                    sample.attributs.append(a)

                    if a.fixed_value == True and a.widget != "checkbox" and a.widget != "hiding_checkbox":
                        DBSession.flush()
                    #if values of the attribute are free
                    elif a.fixed_value == False and a.widget != "checkbox" and a.widget != "hiding_checkbox":
                        av = Attributs_values()
                        av.attribut_id = a.id
                        av.value = None
                        av.deprecated = False
                        DBSession.add(av)
                        DBSession.flush()
                        (sample.a_values).append(av)
                        DBSession.flush()
                    elif a.widget == "checkbox" or a.widget == "hiding_checkbox":
                        found = False
                        for v in a.values:
                            if not check_boolean(v.value) and v.value is not None:
                                (sample.a_values).append(v)
                                found = True
                        if not found:
                            av = Attributs_values()
                            av.attribut_id = a.id
                            av.value = False
                            av.deprecated = False
                            DBSession.add(av)
                            DBSession.flush()
                            (sample.a_values).append(av)
                            DBSession.flush()

        list_sample_id = []
        list_sample_id.append(sample.id)

        #HTSstation/BioScript special case
        if "task_id" in backup_dico:
            for k in fu_dico:
                filename = fu_dico[k][0]
                sha1 = k
                tmp_path = fu_dico[k][1]
                filename_tmp = filename.split('.')
                name_without_ext = filename_tmp[0]
                meas = create_meas(user, new_meas, name_without_ext, description, False,
                False, list_sample_id, None, dest_raw, dest_processed)
                #file upload management
                existing_fu = DBSession.query(Files_up).filter(Files_up.sha1 == sha1).first()
                manage_fu(existing_fu, meas, public_dirname, filename, sha1, None, file_path, True, dest_raw, dest_processed, tmp_path, lab)
                meas.description = meas.description + "\nAttached file uploaded from : " + project_name
                DBSession.add(meas)
                DBSession.flush()
                list_meas_ids_created.append(meas.id)
                #measurement dynamicity
                lab_attributs = DBSession.query(Attributs).filter(and_(Attributs.lab_id == lab_id, Attributs.deprecated == False, Attributs.owner == "measurement")).all()
                if len(lab_attributs) > 0:
                    for a in lab_attributs:
                        meas.attributs.append(a)

                        if a.fixed_value == True and a.widget != "checkbox" and a.widget != "hiding_checkbox":
                            DBSession.flush()
                        #if values of the attribute are free
                        elif a.fixed_value == False and a.widget != "checkbox" and a.widget != "hiding_checkbox":
                            av = Attributs_values()
                            av.attribut_id = a.id
                            av.value = None
                            av.deprecated = False
                            DBSession.add(av)
                            DBSession.flush()
                            (meas.a_values).append(av)
                            DBSession.flush()
                        elif a.widget == "checkbox" or a.widget == "hiding_checkbox":
                            found = False
                            for v in a.values:
                                if not check_boolean(v.value) and v.value is not None:
                                    (meas.a_values).append(v)
                                    found = True
                            if not found:
                                av = Attributs_values()
                                av.attribut_id = a.id
                                av.value = False
                                av.deprecated = False
                                DBSession.add(av)
                                DBSession.flush()
                                (meas.a_values).append(av)
                                DBSession.flush()
                #answer for HTSstation
                if "callback" in backup_dico:
                    return str(backup_dico["callback"]) + "(" + json.dumps({"project_id": project.id, "meas_ids": list_meas_ids_created, "key": task_id}) + ")"
                else:
                    print "no call back"
                    return json.dumps({"error": "No callback detected"})

        #others webapps (HTSstation, BioScript, ...)
        else:
            filename_tmp = filename.split('.')
            name_without_ext = filename_tmp[0]
            meas = create_meas(user, new_meas, name_without_ext, description, False,
                False, list_sample_id, None, dest_raw, dest_processed)

            #file upload management
            existing_fu = DBSession.query(Files_up).filter(Files_up.sha1 == sha1).first()
            #from HTSstation
            HTS = False
            if tmp_path.startswith("/data") or tmp_path.startswith("/archive/epfl"):
                try:
                    manage_fu_from_HTS(existing_fu, meas, filename, sha1, file_path, tmp_path)
                    HTS = True
                except:
                    if "callback" in backup_dico:
                        return str(backup_dico["callback"]) + "(" + json.dumps({"error": "Problem with the file path"}) + ")"
                    else:
                        print "no call back"
                        return json.dumps({"error": "No callback detected"})

            #not from HTSstation
            else:
                manage_fu(existing_fu, meas, public_dirname, filename, sha1, None, file_path, True, dest_raw, dest_processed, tmp_path, lab)
            #nice description's end
            meas.description = meas.description + "\nAttached file uploaded from : " + project_name
            DBSession.add(meas)
            DBSession.flush()
            #measurement dynamicity
            lab_attributs = DBSession.query(Attributs).filter(and_(Attributs.lab_id == lab_id, Attributs.deprecated == False, Attributs.owner == "measurement")).all()
            if len(lab_attributs) > 0:
                for a in lab_attributs:
                    meas.attributs.append(a)

                    if a.fixed_value == True and a.widget != "checkbox" and a.widget != "hiding_checkbox":
                        DBSession.flush()
                    #if values of the attribute are free
                    elif a.fixed_value == False and a.widget != "checkbox" and a.widget != "hiding_checkbox":
                        av = Attributs_values()
                        av.attribut_id = a.id
                        av.value = None
                        av.deprecated = False
                        DBSession.add(av)
                        DBSession.flush()
                        (meas.a_values).append(av)
                        DBSession.flush()
                    elif a.widget == "checkbox" or a.widget == "hiding_checkbox":
                        found = False
                        for v in a.values:
                            if not check_boolean(v.value) and v.value is not None:
                                (meas.a_values).append(v)
                                found = True
                        if not found:
                            av = Attributs_values()
                            av.attribut_id = a.id
                            av.value = False
                            av.deprecated = False
                            DBSession.add(av)
                            DBSession.flush()
                            (meas.a_values).append(av)
                            DBSession.flush()

            if HTS:
                #add sample(s) and measurements for extension selected in HTSstation
                ext_list_bu = backup_dico["ext_list"]
                ext_list = ext_list_bu.split(",")
                module = backup_dico["module"]
                if len(ext_list) == 1 and ext_list[0] == "":
                    pass
                else:
                    ok_or_not = self.create_from_ext_list(ext_list, project, sample_type, module)
                    if "error" in ok_or_not:
                        return json.dumps(ok_or_not)
                    list_meas_ids_created = ok_or_not["meas_id"]

                #answer for HTSstation
                if "callback" in backup_dico:
                    list_meas_ids_created.append(meas.id)
                    return str(backup_dico["callback"]) + "(" + json.dumps({"project_id": project.id, "meas_ids": list_meas_ids_created, "key": project.description}) + ")"
                else:
                    print "no call back"
                    return json.dumps({"error": "No callback detected"})
            #or normal redirect for others
            else:
                flash("Your measurement id " + str(meas.id) + " was succesfully saved into BioRepo")
                raise redirect(url('/search'))

    @expose('biorepo.templates.new_trackhub')
    def trackHubUCSC(self, *args, **kw):
        '''
        :meas_id in kw is a string of one or several measurements id which are coma separated
        '''
        meas_ids = kw.get("meas_id", None)
        list_meas = []
        try:
            #several ids case
            for i in meas_ids.split(','):
                measu = DBSession.query(Measurements).filter(Measurements.id == i).all()
                for j in measu:
                    list_meas.append(j)
        except:
            #single id case
            for i in meas_ids:
                measu = DBSession.query(Measurements).filter(Measurements.id == i).all()
                for j in measu:
                    list_meas.append(j)
        list_extensions = []
        list_assemblies = []
        for m in list_meas:
            #test if export out of BioRepo is allowed
            if m.status_type == False:
                flash("One or several measurements selected are not allowed to get out of BioRepo. Edit them from private to public if you can/want", 'error')
                return redirect(url('/search'))

            #test extensions
            list_file = m.fus
            if len(list_file) > 0:
                for f in list_file:
                    ext = f.extension
                    if ext not in list_extensions:
                        list_extensions.append(ext)
            else:
                flash("One or several measurements selected don't get file attached (just url). Impossible to link it/them into a trackhub", 'error')
                return redirect(url('/search'))

            #test assembly
            list_attributs = m.attributs
            for a in list_attributs:
                if a.key == "assembly":
                    list_assembly_values = a.values
                    for v in list_assembly_values:
                        if v in m.a_values and v.value not in list_assemblies:
                            list_assemblies.append(v.value)
        if len(list_extensions) > 1:
            flash("Different type of extensions are not allowed.", 'error')
            return redirect(url('/search'))
        elif len(list_assemblies) > 1:
            flash("Different assemblies are not allowed.", 'error')
            return redirect(url('/search'))
        elif len(list_extensions) == 0:
            flash("Problem with file extension : not found", 'error')
            return redirect(url('/search'))
        elif len(list_assemblies) == 0:
            flash("You must set assembly to your measurements. Edit them.", 'error')
            return redirect(url('/search'))

        files = []
        for m in list_meas:
            for f in m.fus:
                if f not in files:
                    files.append(f)
        for a in list_assemblies:
            assembly = a
        for e in list_extensions:
            extension = e

        #fill the form
        new_th = NewTrackHub(action=url('/measurements/post_trackHub')).req()
        new_th.child.children[0].placeholder = "Your trackhub name..."
        new_th.child.children[1].value = assembly
        new_th.child.children[2].options = [(f.id, '%s' % f.filename, {'selected': True}) for f in files]
        new_th.child.children[3].value = extension

        return dict(page='measurements/trackhub', widget=new_th)

    @expose()
    def post_trackHub(self, *args, **kw):
        '''
        build and put the trackhubs on bbcf-serv01 to /data/epfl/bbcf/biorepo/trackhubs/LAB/USERMAIL
        '''
        #Thx to Jonathan SOBEL (jonathan.sobelATepfl.ch) for his help.
        #He read the entire UCSC TrackHub Doc (even Chuck Norris did not) and explained it to me. This man is a hero.
        ## /!\ Don't forget to symlink the trackHubs path into the /public directory during the BioRepo installation /!\
        assembly = str(kw["assembly"])
        extension = str(kw["extension"])
        file_ids = kw["files"]

        hostname = socket.gethostname().lower()
        #because of aliasing
        if hostname == "ptbbsrv2.epfl.ch":
            hostname = "biorepo.epfl.ch"

        dico_ext_container = {"bigwig": "multiWig", "bw": "multiWig", "bigbed": "multiBed", "bam": "multiBam"}
        dico_ext_type = {"bw": "bigWig", "bigWig": "bigWig", "bb": "bigBed", "bigbed": "bigBed", "bam": "bam"}
        #check extension
        if extension not in dico_ext_type.keys():
            flash("This extension " + str(extension) + " is not supported by UCSC Trackhub.", 'error')
            raise redirect(url('/search'))
        #paths preparation
        th_dest_path = "/data/epfl/bbcf/biorepo/trackHubs/"
        user = handler.user.get_user_in_session(request)
        user_lab = session.get('current_lab', None)
        if user_lab is None:
            flash("Lab error. Report it to your administrator", 'error')
            raise redirect(url('/search'))
        tmp_mail = (user._email).split('@')
        user_mail = tmp_mail[0] + "AT" + tmp_mail[1]
        path_completion = user_lab + "/" + user_mail + "/"
        lab_path = th_dest_path + user_lab
        final_path = th_dest_path + path_completion
        #building destination path if not built yet
        try:
            if not os.path.exists(lab_path):
                os.mkdir(lab_path)
                os.mkdir(final_path)
            if not os.path.exists(final_path):
                os.mkdir(final_path)
        except:
            print "!!!!!!!!!!!!!! /data/epfl/bbcf/biorepo/trackhubs/ NOT ACCESSIBLE !!!!!!!!!!!!!!!!!"
            flash("Internal error. /data is not accessible. You can contact your administrator.", "error")
            raise redirect(url('/search'))

        if kw['name'] == u'':
            #generate a random name
            kw['name'] = str(uuid.uuid4()).split('-')[0]
        kw['name'] = kw['name'].encode('ascii', 'ignore')
        kw['name'] = kw['name'].replace(' ', '_')
        trackhub_dest = final_path + kw['name']

        kw['name'] = str(kw['name'])

        #if a directory with the same name is here
        if os.path.exists(trackhub_dest):
            trackhub_dest = trackhub_dest + "_" + str(uuid.uuid4()).split('-')[0]
            os.mkdir(trackhub_dest)
        else:
            os.mkdir(trackhub_dest)
        #last directory level creation
        assembly_path = trackhub_dest + "/" + assembly
        os.mkdir(assembly_path)
        ########### end of the directories creation #############
        #time to create hub.txt, genome.txt, /assembly and /assembly/trackDB.txt
        hub = trackhub_dest + "/hub.txt"
        genome = trackhub_dest + "/genomes.txt"
        trackDB = assembly_path + "/trackDb.txt"
        #hub.txt - give the trackhub path to UCSC and others nominative information
        shortLabel = str(kw['name']).split('_')[0]
        longLabel = str(kw['name'])
        #short and long lab can't be the same (stupid UCSC...)
        if shortLabel == longLabel:
            longLabel = longLabel + "_1"
        with open(hub, "a") as h:
            h.write("hub " + trackhub_dest.split('/')[-1] + "\n" + "shortLabel " + shortLabel + "\n" +
                "longLabel " + longLabel + "\n" + "genomesFile genomes.txt" + "\n" +
                "email " + str(user._email) + "\n")
        #genome.txt - first line assembly, second line trackDB.txt path
        with open(genome, "a") as g:
            g.write("genome " + assembly + "\n" + "trackDb " + assembly + "/trackDb.txt")
        #trackDB.txt - THE important file of the thing, big thx to UCSC and guys who developped it for the horrible way to build all this sh*t ><
        with open(trackDB, "a") as t:
            #file header
            t.write("track " + str(kw['name']) + "\n" + "container " + dico_ext_container[extension.lower()] + "\n" +
                "shortLabel " + shortLabel + "\n" + "longLabel " + longLabel + "\n" +
                "type " + dico_ext_type[extension.lower()] + "\n" + "visibility full\n" + "maxHeightPixels 70:70:32\n" + "configurable on\n" +
                "aggregate transparentOverlay\n" + "showSubtrackColorOnUi on\n" + "priority 1.0\n\n")
            #tracks
            list_files = []
            try:
                #several ids case
                for i in file_ids.split(','):
                    fu = DBSession.query(Files_up).filter(Files_up.id == i).all()
                    for j in fu:
                        list_files.append(j)
            except:
                #single id case
                for i in file_ids:
                    fu = DBSession.query(Files_up).filter(Files_up.id == i).all()
                    for j in fu:
                        list_files.append(j)
            for f in list_files:
                name_tmp = str(f.filename).split('.')
                real_name = name_tmp[0]
                t.write("\t" + "track " + str(f.filename) + "\n" +
                        "\t" + "parent " + str(kw['name']) + "\n" +
                        "\t" + "bigDataUrl http://" + hostname + url("/public/public_link?sha1=" + str(f.sha1) + "\n" +
                        "\t" + "shortLabel " + shortLabel + "\n" +
                        "\t" + "longLabel " + real_name + "\n" +
                        "\t" + "type " + dico_ext_type[extension.lower()] + "\n" +
                        "\t" + "autoScale on" + "\n" +
                        "\t" + "color " + str(randint(0, 255)) + "," + str(randint(0, 255)) + "," + str(randint(0, 255)) + "\n\n"))

        #build the final hub_url accessible
        track_name = hub.split('/')[-2]
        hub_name = hub.split('/')[-1]
        hub_url = "http://" + hostname + url("/trackHubs/") + user_lab + "/" + user_mail + "/" + track_name + "/" + hub_name
        try:
            print "####### Trackhub " + longLabel + " successfully created by " + str(user.firstname) + " " + str(user.name)
        except:
            print "####### Trackhub " + longLabel + " successfully created by " + str(user.name)
        raise redirect('http://genome.ucsc.edu/cgi-bin/hgTracks?hubUrl=' + hub_url + "&db=" + assembly)

    @expose()
    def buildZip(self, list_meas):
        #build tmp directory
        path_tmp = tempfile.mkdtemp(dir=archives_path())
        os.chmod(path_tmp, 0755)
        tab_file = path_tmp + "/aboutTheseFiles.tab"
        list_meas_id = list_meas.split(',')
        references = []
        paths = {}
        #build the tab file header
        with open(tab_file, "a") as tab:
            tab.write("Project name\tSample Name\tTechnique used\tAssembly\tMeasurement name(BioRepo id)\tFilename\tDescription\tSize\n")
        #collect information about each measurement selected
        for i in list_meas_id:
            meas = DBSession.query(Measurements).filter(Measurements.id == i).first()
            m_name = meas.name
            description = meas.description
            if description is None:
                description = ''
            description = description.replace("\t", " ")
            if len(meas.fus) > 0:
                for f in meas.fus:
                    path_fu = f.path + "/" + f.sha1
                    filename = f.filename
                    file_size = os.path.getsize(path_fu)
                    size = display_file_size(file_size)
                    paths[path_fu] = filename
                    list_samples = meas.samples
                    #objects list
                    attributs = meas.attributs
                    attributs_ids = []
                    for a in attributs:
                        if a.key == "assembly":
                            attributs_ids.append(a.id)
                    a_values = meas.a_values
                    assembly = 'not specified'
                    for v in a_values:
                        if v.attribut_id in attributs_ids:
                            assembly = v.value
                    for s in list_samples:
                        s_name = s.name
                        s_type = s.type
                        project_id = s.project_id
                        project = DBSession.query(Projects).filter(Projects.id == project_id).first()
                        project_name = project.project_name
                        m_name = m_name + '(' + i + ')'
                        #write information in the tab file
                        with open(tab_file, "a") as tab:
                            tab.write(("\t".join([project_name, s_name, s_type, assembly, m_name, filename, description, size])).replace('\n', ' ') + '\n')
            else:
                references.append(meas.id)

        if len(references) > 0:
            msg = "--- DO NOT REPLY TO THIS MESSAGE PLEASE ---\nYour selection contains reference(s) to other(s) website(s). Guilty measurement(s) id(s) : " + str(references) + ". BioRepo didn't find any file in its database. It is not yet able to zip referenced file(s). Contact the administrator if this feature is usefull for you and your lab."
        else:
            zip_name = "BioRepo_Archive.zip"
            zip_path = path_tmp + '/' + zip_name
            path_to_give = path_tmp.split("/")[-1] + "/" + zip_name
            with MyZipFile(zip_path, 'w') as myZip:
                for p in paths.keys():
                    #build symlink with goodfilename
                    source = p
                    to_replace = p.split('/')[-1]
                    dest = p.replace(to_replace, paths[p])
                    if os.path.exists(dest):
                        pass
                    else:
                        os.symlink(source, dest)
                    myZip.write(dest, dest.split('/')[-1], zipfile.ZIP_DEFLATED)
                    #delete the useless symlink
                    os.remove(dest)
                myZip.write(tab_file, tab_file.split('/')[-1], zipfile.ZIP_DEFLATED)
            msg = "--- DO NOT REPLY TO THIS MESSAGE PLEASE ---\nA 24h available public link was generated by BioRepo to download your .zip file : http://biorepo.epfl.ch/biorepo/public/getZip?pzip=" + path_to_give
            os.chmod(zip_path, 0755)
        return msg

    @expose()
    def sendMail(self, user_mail, msg):
        msg = MIMEText(msg)
        msg["From"] = "webmaster.bbcf@epfl.ch"
        msg["To"] = user_mail
        msg["Subject"] = "[DO NOT REPLY] Your BioRepo zip archive is available"
        p = Popen(["/usr/sbin/sendmail", "-t"], stdin=PIPE)
        p.communicate(msg.as_string())

    @expose()
    def zipWorkflow(self, list_meas, user_mail):
        try:
            msg = self.buildZip(list_meas)
        except:
            msg = "An error occured during your zip building. Please contact the administrator. NB : It's impossible to build a ZIP file that exceeds 4Gb."
            print " --------------- ZIP BUILDING ERROR ------------ measurements : " + str(list_meas) + "; user : " + str(user_mail)
            print_traceback()
        try:
            self.sendMail(user_mail, msg)
        except:
            print "---------  Mail didn't send to " + str(user_mail) + ". The message was : " + str(msg) + " -----------"
            print_traceback()

    @expose()
    def zipThem(self, *args, **kw):
        """
        build zip archive + csv file with description of the selected files
        """
        #get list of the meas_id selected
        list_meas = str(kw.get("list_meas", None))
        user = handler.user.get_user_in_session(request)
        user_mail = user._email
        if list_meas == "null":
            flash("Select something if you want to use this functionality...", "error")
            raise redirect(url('/search'))
        else:
            asyncjob_perform(self.zipWorkflow, list_meas, user_mail)
            flash("BioRepo is building your zip. A link to download it will be sent to you by email at the end of the processing.")
            raise redirect(url('/search'))

    @expose('biorepo.templates.info_meas')
    def info_meas(self, *args, **kw):
        """
        return all the information about a selected measurement in search page
        input : meas_id from selected measurement
        output: final_dic = {'meas': {'meas_attr': 'val'}, 'samples': [{'sample_attr': 'val'}, {'sample_attr': 'val'}], 'project': {'project_attr': 'val'}}
        """
        meas_id = kw.get("meas_id", None)
        #meas_id = 8
        meas = {}
        final_dic = {}
        meas_queried = DBSession.query(Measurements).filter(Measurements.id == meas_id).first()
        if meas_queried is None:
            flash("Measurement not found in the database. Contact the administrator.", "error")
            raise redirect(url('/search'))
        #check user lab
        list_att = meas_queried.attributs
        lab_id = list_att[0].lab_id
        lab_to_check = DBSession.query(Labs).filter(Labs.id == lab_id).first()
        current_lab = session.get("current_lab")

        if lab_to_check.name != current_lab:
            flash("This is not a measurement from the lab currently saved in this active session (" + current_lab + "). You're not allowed to access to it. Sorry.. You're not allowed to access to it. Sorry.", "error")
            raise redirect(url('/search'))
        #measurements
        parents = meas_queried.parents
        children = meas_queried.children
        for m in meas_queried.__dict__.keys():
            if m != "_sa_instance_state" and m != "date" and m != "attributs":
                if m == "type":
                    if meas_queried.__dict__[m]:
                        meas[m] = "raw"
                    else:
                        meas[m] = "processed"
                elif m == "status_type":
                    if meas_queried.__dict__[m]:
                        meas[m] = "public"
                    else:
                        meas[m] = "private"
                elif m == "user_id":
                    u = DBSession.query(User).filter(User.id == meas_queried.__dict__[m]).first()
                    meas["owner"] = u.firstname[0] + ". " + u.name
                elif m == "parents":
                    if len(parents) == 0:
                        meas["parent(s) id"] = "No parent(s) referenced"
                    else:
                        list_p = []
                        for p in parents:
                            list_p.append(str(p.id))
                        p_string = ", ".join(list_p)
                        meas["parent(s) id"] = p_string
                elif m == "children":
                    if len(children) == 0:
                        meas["children id"] = "No children referenced"
                    else:
                        list_c = []
                        for c in children:
                            list_c.append(str(c.id))
                            c_string = ", ".join(list_c)
                        meas["children id"] = c_string
                else:
                    meas[m] = meas_queried.__dict__[m]
        #dynamic fields
        a_val_meas = meas_queried.a_values
        for a_val in a_val_meas:
            att_id = a_val.attribut_id
            value = a_val.value
            att = DBSession.query(Attributs).filter(Attributs.id == att_id).first()
            att_key = att.key
            if att.widget == "checkbox" or att.widget == "hiding_checkbox":
                value = check_boolean(value)
                if value:
                    value = str(att_key)
                else:
                    value = "Not " + str(att_key)
            meas[att_key] = value
        #file
        files_up = meas_queried.fus
        if len(files_up) > 0:
            #just one file in files_up
            for f in files_up:
                meas["filename"] = f.filename
        else:
            meas["filename"] = "Measurement without attached file."

        final_dic["meas"] = meas
        #SAMPLE(S) for selected measurement
        final_dic["samples"] = []
        list_samples = meas_queried.samples
        project_ids = []
        done_samples = []
        for sample in list_samples:
            samples_from_meas = {}
            if len(list_samples) == 0:
                project_from_meas = {}
                samples_from_meas["No sample"] = "Measurement without sample(s)."
                project_from_meas["No project"] = "Measurement without project(s)."
                final_dic["samples"].append(samples_from_meas)
                final_dic["project"] = project_from_meas
                return dict(
                    page='info_meas',
                    dico=final_dic,
                    value=kw
                    )
            else:
                if sample not in done_samples:
                    for s in sample.__dict__.keys():
                        if s != "_sa_instance_state" and s != "date":
                            samples_from_meas[s] = sample.__dict__[s]
                        if s == "project_id":
                            if sample.__dict__[s] not in project_ids:
                                project_ids.append(sample.__dict__[s])
                    #dynamic fields
                    a_val_sample = sample.a_values
                    for a_val in a_val_sample:
                        att_id = a_val.attribut_id
                        value = a_val.value
                        att = DBSession.query(Attributs).filter(Attributs.id == att_id).first()
                        att_key = att.key
                        if att.widget == "checkbox" or att.widget == "hiding_checkbox":
                            value = check_boolean(value)
                            if value:
                                value = str(att_key)
                            else:
                                value = "Not " + str(att_key)
                        samples_from_meas[att_key] = value
                    final_dic["samples"].append(samples_from_meas)
            done_samples.append(sample)
        #PROJECT for selected meas
        final_dic["projects"] = []
        for p_id in project_ids:
            project_from_meas = {}
            project = DBSession.query(Projects).filter(Projects.id == p_id).first()
            for p in project.__dict__.keys():
                if p != "_sa_instance_state" and p != "date":
                    if p == "user_id":
                        u = DBSession.query(User).filter(User.id == project.__dict__[p]).first()
                        project_from_meas["owner"] = u.firstname[0] + ". " + u.name
                    else:
                        project_from_meas[p] = project.__dict__[p]
            final_dic["projects"].append(project_from_meas)
        return dict(
            page='info_meas',
            dico=final_dic,
            value=kw
            )
