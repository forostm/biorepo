# -*- coding: utf-8 -*-
"""Project Controller"""
from tgext.crud import CrudRestController
from biorepo.lib.base import BaseController
import tg
from tg import expose, flash, request, validate, url, session
from repoze.what.predicates import has_any_permission
from tg.controllers import redirect
from biorepo.widgets.forms import NewProject, EditProject
from biorepo.widgets.datagrids import ProjectGrid
from biorepo.model import DBSession, Projects, Samples, User, Labs, Attributs
from tg.decorators import with_trailing_slash
from biorepo import handler
from biorepo.lib import util
from biorepo.lib.util import isAdmin
from biorepo.model.auth import Permission
from tg import app_globals as gl
from biorepo.model import DBSession, Permission
from sqlalchemy import and_


__all__ = ['ProjectController']


class ProjectController(BaseController):
    allow_only = has_any_permission(gl.perm_admin, gl.perm_user)

    @with_trailing_slash
    @expose('biorepo.templates.list')
    @expose('json')
    def index(self, *args, **kw):
        user = handler.user.get_user_in_session(request)
        user_lab = session.get("current_lab", None)
        admins = tg.config.get('admin.mails')
        mail = user.email
        if user_lab and mail not in admins:
            lab = DBSession.query(Labs).filter(Labs.name == user_lab).first()
            projects = [p for p in user.projects if p in lab.projects]
        elif mail in admins:
            projects = DBSession.query(Projects).all()
        else:
            projects = None

        all_projects = [util.to_datagrid(ProjectGrid(), projects, "Projects Table", len(projects) > 0)]

        return dict(page='projects', model='project', form_title="new project", items=all_projects, value=kw)

    @expose('biorepo.templates.new_project')
    def new(self, **kw):
        #get the logged user
        user = handler.user.get_user_in_session(request)
        user_lab = session.get("current_lab", None)
        samples = []
        if user_lab is not None:
            lab = DBSession.query(Labs).filter(Labs.name == user_lab).first()
            attributs = DBSession.query(Attributs).filter(and_(Attributs.lab_id == lab.id, Attributs.deprecated == False)).all()
            projects = [p.id for p in user.projects if p in lab.projects]
            for a in attributs:
                for s in a.samples:
                    if s not in samples and s.project_id in projects:
                        samples.append(s)
        new_form = NewProject(action=url('/projects/post')).req()
        new_form.child.children[0].placeholder = "Your project name..."
        new_form.child.children[1].placeholder = "Your commments here..."
        new_form.child.children[2].options = [(sample.id, '%s' % (sample.name)) for sample in samples]

        return dict(page='projects', widget=new_form)

    @expose('biorepo.templates.edit_project')
    def edit(self, *args, **kw):

        user = handler.user.get_user_in_session(request)
        user_lab = session.get("current_lab", None)
        if user_lab is not None:
            lab = DBSession.query(Labs).filter(Labs.name == user_lab).first()
        admin = isAdmin(user)
        project = DBSession.query(Projects).filter(Projects.id == args[0]).first()
        samples = []
        if admin:
            samples = DBSession.query(Samples).all()
        else:
            attributs = DBSession.query(Attributs).filter(and_(Attributs.lab_id == lab.id, Attributs.deprecated == False)).all()
            projects = [p.id for p in user.projects if p in lab.projects]
            for a in attributs:
                for s in a.samples:
                    if s not in samples and s.project_id in projects:
                        samples.append(s)

        if project.user_id == user.id or admin:
            edit_form = EditProject(action=url('/projects/post_edit'))
            edit_form.child.children[0].value = project.id
            edit_form.child.children[1].value = project.project_name
            edit_form.child.children[2].value = project.description
            list_unselected = [s for s in samples if s not in project.samples]
            samples_selected = [(sample.id, '%s' % (sample.name)) for sample in list_unselected] + [(sample.id, '%s' % (sample.name), {'selected': True}) for sample in project.samples]
            edit_form.child.children[3].options = samples_selected

            list_selected = []
            for x in samples_selected:
                #take only those with "selected : True"
                if len(x) > 2:
                    list_selected.append(x[0])
            edit_form.child.children[4].value = list_selected

            return dict(page='projects', widget=edit_form, value=kw)
        else:
            flash("It is not your project -> you are not allowed to edit it", 'error')
            raise redirect('/projects')

    @expose('json')
    def create(self, *args, **kw):
        user = handler.user.get_user_in_session(request)
        project = Projects()
        name = kw.get('project_name', None)
        if name is None:
            return {'ERROR': "You have to give a name to your project"}
        project.project_name = name
        lab_id = kw['lab']
        if lab_id is None:
            return {'ERROR': "We need to know the user's lab"}
        lab = DBSession.query(Labs).filter(Labs.id == lab_id).first()
        (project.labs).append(lab)
        #test if user is an admin
        admin = isAdmin(user)
        if admin:
            project.user_id = kw.get('user_id', user.id)
        else:
            project.user_id = user.id

        project.description = kw.get('description', None)
        get_samples = kw.get('samples', None)
        l = []

        if get_samples is None:
            project.samples = l
        else:
            for x in get_samples.split(','):
                sam = DBSession.query(Samples).join(Projects).join(User).filter(Samples.id == x).first()
                l.append(sam)

            project.samples = l
        #checking print
        print project, " building project with wget"

        DBSession.add(project)
        DBSession.flush()

        return {"user_id": user.id, "user_name": user.name, "project_id": project.id, "project_name": project.project_name,
                 "description": project.description}

    @expose()
    def post(self, *args, **kw):
        user = handler.user.get_user_in_session(request)
        user_lab = session.get("current_lab", None)
        if user_lab:
            lab = DBSession.query(Labs).filter(Labs.name == user_lab).first()
        p = Projects()
        if kw['project_name'] == '':
            flash("Bad Project : Your project must have a name", "error")
            raise redirect("./new")
        p.project_name = kw['project_name']
        p.user_id = user.id
        p.description = kw.get('description', None)
        (p.labs).append(lab)
        DBSession.add(p)
        DBSession.flush()
        flash("Project created !")
        raise redirect('/projects')

    @expose()
    def post_edit(self, *args, **kw):
        id_project = kw["IDselected"]
        project = DBSession.query(Projects).filter(Projects.id == id_project).first()
        if kw['project_name'] == '':
            flash("Bad Project : Your project must have a name", "error")
            raise redirect("./edit/" + id_project)
        project.project_name = kw["project_name"]
        project.description = kw["description"]
        samples_ids = kw.get("samples", None)
        if samples_ids is not None:
            if not isinstance(samples_ids, (list, tuple)):
                samples_ids = [int(samples_ids)]
            else:
                #from unicode to integer for comparison
                list_tmp = []
                for i in samples_ids:
                    i = int(i)
                    list_tmp.append(i)
                samples_ids = list_tmp
        else:
            samples_ids = []

        #check if sample is not deleted
        try:
            if kw["selected_samples"] != "[]":
                old_selected = [int(x) for x in kw["selected_samples"].replace("[", "").replace("]", "").split(",")]
            else:
                old_selected = []
        except:
            flash("Samples id error, please contact the administrator to report your bug", 'error')
            print "Something changed with this Turbogears version.... controllers/project.py l180 --> JSON solution is better"
            raise redirect("./")

        list_names = []
        for o in old_selected:
            if o not in samples_ids:
                sample1 = DBSession.query(Samples).filter(Samples.id == o).first()
                list_names.append(str(sample1.name))
        if len(list_names) > 0:
            flash("If you choose to delete : " + str(list_names).replace("[", "").replace("]", "") + " from the project, this sample will be removed. The sample deletion is not enabled here. Please do it directly in the sample page delete option.", 'error')
            raise redirect("./edit/" + id_project)

        list_samples = []
        for s in samples_ids:
            sample = DBSession.query(Samples).filter(Samples.id == s).first()
            list_samples.append(sample)

        project.samples = list_samples

        raise redirect("./")

    @validate(EditProject, error_handler=edit)
    @expose('genshi:tgext.crud.templates.put')
    def put(self, *args, **kw):
        user = handler.user.get_user_in_session(request)
        kw['user'] = user.id

        return CrudRestController.put(self, *args, **kw)

    @expose('json')
    def delete(self, *args, **kw):
        user = handler.user.get_user_in_session(request)
        project = DBSession.query(Projects).filter(Projects.id == args[0]).first()
        admin = isAdmin(user)

        if project.user_id == user.id or admin:
            try:
                flash("Your project " + str(project.project_name) + " has been deleted with success")
            except:
                flash("Your project " + (project.project_name) + " has been deleted with success")
            DBSession.delete(project)
            DBSession.flush()
            raise redirect('/projects')
        else:
            flash("It is not your project -> you are not allowed to delete it", 'error')
            raise redirect('/projects')

    @expose('genshi:tgext.crud.templates.get_delete')
    def get_delete(self, *args, **kw):
        user = handler.user.get_user_in_session(request)
        return CrudRestController.get_delete(self, *args, **kw)

    @expose('json')
    def gimme_projects_plz(self, mail, *args, **kw):
        user = DBSession.query(User).filter(User._email == mail).first()
        if user is not None:
            user_id = user.id
            projects = DBSession.query(Projects).filter(Projects.user_id == user_id).all()
            dico_projects_by_user = {}
            if len(projects) != 0:
                for p in projects:
                    dico_projects_by_user[p.id] = {"project_name": p.project_name}
            else:
                dico_projects_by_user = {0: {"project_name": "No projects found into BioRepo for this user"}}
        else:
            dico_projects_by_user = {"error": str(mail) + " is not regristred in BioRepo"}
        return dico_projects_by_user
