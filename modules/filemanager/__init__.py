import mimetypes
import os
import shutil
import re
import tarfile

from django import forms
# from django.core.servers.basehttp import FileWrapper
from wsgiref.util import FileWrapper
from django.core.urlresolvers import reverse
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import render
from django.http import HttpResponseRedirect, HttpResponse
from django.template import RequestContext
from django.utils.translation import ugettext_lazy as _

from unidecode import unidecode
from PIL import Image

from . import settings

path_end = r'(?P<path>[\w\d_ -/.]*)$'

ActionChoices = (
    ('upload', 'upload'),
    ('rename', 'rename'),
    ('delete', 'delete'),
    ('add', 'add'),
    ('move', 'move'),
    ('copy', 'copy'),
)


class FileManagerForm(forms.Form):
    ufile = forms.FileField(required=False)
    action = forms.ChoiceField(choices=ActionChoices)
    path = forms.CharField(max_length=200, required=False)
    name = forms.CharField(max_length=32, required=False)
    current_path = forms.CharField(max_length=200, required=False)
    file_or_dir = forms.CharField(max_length=4)


class FileManager(object):
    """
    maxspace,maxfilesize in KB
    """
    idee = 0

    def __init__(self, basepath, ckeditor_baseurl='', maxfolders=50, maxspace=5 * 1024, maxfilesize=1 * 1024,
                 public_url_base=None, extensions=None, is_admin_view=False):
        if basepath[-1] == os.sep:
            basepath = basepath[:-1]
        if ckeditor_baseurl and ckeditor_baseurl[-1] == os.sep:
            ckeditor_baseurl = ckeditor_baseurl[:-1]
        self.basepath = basepath
        self.ckeditor_baseurl = ckeditor_baseurl
        self.maxfolders = maxfolders
        self.maxspace = maxspace
        self.maxfilesize = maxfilesize
        self.extensions = extensions;
        self.public_url_base = public_url_base
        self.is_admin_view = is_admin_view

    def rename_if_exists(self, folder, file):
        if folder[-1] != '/':
            folder = folder + '/'
        if os.path.exists(folder + file):
            if file.find('.') == -1:
                # no extension
                for i in range(1000):
                    if not os.path.exists(folder + file + '.' + str(i)):
                        break
                return file + '.' + str(i)
            else:
                extension = file[file.rfind('.'):]
                name = file[:file.rfind('.')]
                for i in range(1000):
                    if not os.path.exists(folder + name + '.' + str(i) + extension):
                        break
                return name + '.' + str(i) + extension
        else:
            return file

    def read_in_chunks(self, file_object, chunk_size=1024):
        while True:
            data = file_object.read(chunk_size)
            if not data:
                break
            yield data

    def get_size(self, start_path):
        total_size = 0
        for dirpath, dirnames, filenames in os.walk(start_path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                total_size += os.path.getsize(fp)
        return total_size

    def next_id(self):
        self.idee = self.idee + 1
        return self.idee

    def handle_form(self, form, files):
        action = form.cleaned_data['action']
        path = form.cleaned_data['path']
        name = form.cleaned_data['name']
        ufile = form.cleaned_data['ufile']
        file_or_dir = form.cleaned_data['file_or_dir']
        self.current_path = form.cleaned_data['current_path']
        messages = []
        if name and file_or_dir == 'dir' and not re.match(r'[\w\d_ -]+', name).group(0) == name:
            messages.append(_('Invalid folder name') + ' : ' + name)
            return messages
        if name and file_or_dir == 'file' and (
            re.search('\.\.', name) or not re.match(r'[\w\d_ -.]+', name).group(0) == name):
            messages.append(_('Invalid file name') + ' : ' + name)
            return messages
        if not re.match(r'[\w\d_ -/]+', path).group(0) == path:
            messages.append(_('Invalid path') + ' : ' + path)
            return messages
        if action == 'upload':
            for f in files.getlist('ufile'):
                if re.search('\.\.', f.name) or not re.match('[\w\d_ -/.]+', f.name).group(0) == f.name:
                    messages.append(_('File name is not valid') + ' : ' + f.name)
                elif f.size > self.maxfilesize * 1024:
                    messages.append(_('File size exceeded') + ' ' + str(self.maxfilesize) + " KB : " + f.name)
                elif (settings.FILEMANAGER_CHECK_SPACE and
                          ((self.get_size(self.basepath) + f.size) > self.maxspace * 1024)):
                    messages.append(_('Total Space size exceeded') + ' ' + str(self.maxspace) + " KB : " + f.name)
                elif self.extensions and len(f.name.split('.')) > 1 and f.name.split('.')[-1] not in self.extensions:
                    messages.append(_('File extension not allowed') + ' (.' + f.name.split('.')[-1] + ') : ' + f.name)
                elif self.extensions and len(f.name.split('.')) == 1 and f.name.split('.')[-1] not in self.extensions:
                    messages.append(_('No file extension in uploaded file') + ' : ' + f.name)
                else:
                    filepath = self.basepath + path + self.rename_if_exists(self.basepath + path, f.name)
                    with open(filepath, 'wb') as dest:
                        for chunk in self.read_in_chunks(f):
                            dest.write(chunk)
                    f.close()
            if len(messages) == 0:
                messages.append(_('All files uploaded successfully'))
        elif action == 'add':
            os.chdir(self.basepath)
            no_of_folders = len(list(os.walk('.')))
            if (no_of_folders + 1) <= self.maxfolders:
                try:
                    os.chdir(self.basepath + path)
                    os.mkdir(name)
                    messages.append(_('Folder created successfully') + ' : ' + name)
                except:
                    messages.append(_('Folder couldn\'t be created') + ' : ' + name)
            else:
                messages.append(_('Folder couldn\' be created because maximum number of folders exceeded') + ' : ' +
                    str(self.maxfolders))
        elif action == 'rename' and file_or_dir == 'dir':
            oldname = path.split('/')[-2]
            path = os.sep.join(path.split('/')[:-2])
            try:
                os.chdir(self.basepath + path)
                os.rename(oldname, name)
                messages.append(_('Folder renamed successfully from') + ' ' + oldname + ' ' + _('to') + ' ' + name)
            except:
                messages.append(_('Folder couldn\'t renamed to') + ' ' + name)
        elif action == 'delete' and file_or_dir == 'dir':
            if path == '/':
                messages.append(_('Root folder can\'t be deleted'))
            else:
                name = path.split('/')[-2]
                path = os.sep.join(path.split('/')[:-2])
                try:
                    os.chdir(self.basepath + path)
                    shutil.rmtree(name)
                    messages.append(_('Folder deleted successfully') + ' : ' + name)
                except:
                    messages.append(_('Folder couldn\'t deleted') + ' : ' + name)
        elif action == 'rename' and file_or_dir == 'file':
            oldname = path.split('/')[-1]
            old_ext = oldname.split('.')[1] if len(oldname.split('.')) > 1 else None
            new_ext = name.split('.')[1] if len(name.split('.')) > 1 else None
            if old_ext == new_ext:
                path = os.sep.join(path.split('/')[:-1])
                try:
                    os.chdir(self.basepath + path)
                    os.rename(oldname, name)
                    messages.append(_('File renamed successfully from') + ' ' + oldname + ' ' + _('to') + ' ' + name)
                except:
                    messages.append(_('File couldn\'t be renamed to') + ' ' + name)
            else:
                if old_ext:
                    messages.append(_('File extension should be same') + ' : .' + old_ext)
                else:
                    messages.append(_('New file extension didn\'t match with old file extension'))
        elif action == 'delete' and file_or_dir == 'file':
            if path == '/':
                messages.append(_('Root folder can\'t be deleted'))
            else:
                name = path.split('/')[-1]
                path = os.sep.join(path.split('/')[:-1])
                try:
                    os.chdir(self.basepath + path)
                    os.remove(name)
                    messages.append(_('File deleted successfully') + ' : ' + name)
                except:
                    messages.append(_('File couldn\'t deleted') + ' : ' + name)
        elif action == 'move' or action == 'copy':
            # from path to current_path
            if self.current_path.find(path) == 0:
                messages.append(_('Cannot move/copy to a child folder'))
            else:
                path = os.path.normpath(path)  # strip trailing slash if any
                if os.path.exists(self.basepath + self.current_path + os.path.basename(path)):
                    messages.append(_('ERROR: A file/folder with this name already exists in the destination folder.'))
                else:
                    if action == 'move':
                        method = shutil.move
                    else:
                        if file_or_dir == 'dir':
                            method = shutil.copytree
                        else:
                            method = shutil.copy
                    try:
                        method(self.basepath + path, self.basepath + self.current_path + os.path.basename(path))
                    except:
                        messages.append(_('File/folder couldn\'t be moved/copied.'))
        return messages

    def directory_structure(self):
        self.idee = 0
        dir_structure = {'': {'id': self.next_id(), 'open': 'yes', 'dirs': {}, 'files': []}}
        os.chdir(self.basepath)
        for directory, directories, files in os.walk('.'):
            directory_list = directory[1:].split(os.sep)
            current_dir = None
            nextdirs = dir_structure
            for d in directory_list:
                current_dir = nextdirs[d]
                nextdirs = current_dir['dirs']
            if directory[1:] + os.sep == self.current_path:
                self.current_id = current_dir['id']
            current_dir['dirs'].update(
                dict(map(lambda d: (d, {'id': self.next_id(), 'open': 'no', 'dirs': {}, 'files': []}), directories)))
            current_dir['files'] = files
        return dir_structure

    def media(self, path):
        ext = path.split('.')[-1]
        try:
            mimetypes.init()
            mimetype = mimetypes.guess_type(path)[0]
            img = Image.open(self.basepath + os.sep + path)
            width, height = img.size
            mx = max([width, height])
            w, h = width, height
            if mx > 60:
                w = width * 60 / mx
                h = height * 60 / mx
            img = img.resize((w, h), Image.ANTIALIAS)
            response = HttpResponse(content_type=mimetype or "image/" + ext)
            response['Cache-Control'] = 'max-age=3600'
            img.save(response, mimetype.split('/')[1] if mimetype else ext.upper())
            return response
        except Exception as e:
            imagepath = settings.FILEMANAGER_STATIC_ROOT + 'images/icons/' + ext + '.png'
            if not os.path.exists(imagepath):
                imagepath = settings.FILEMANAGER_STATIC_ROOT + 'images/icons/default.png'
            img = Image.open(imagepath)
            width, height = img.size
            mx = max([width, height])
            w, h = width, height
            if mx > 60:
                w = int(width * 60 / mx)
                h = int(height * 60 / mx)
            img = img.resize((w, h), Image.ANTIALIAS)
            response = HttpResponse(content_type="image/png")
            response['Cache-Control'] = 'max-age:3600'
            img.save(response, 'png')
            return response

    def download(self, path, file_or_dir):
        if not re.match(r'[\w\d_ -/]*', path).group(0) == path:
            return HttpResponse('Invalid path')
        if file_or_dir == 'file':
            filepath = self.basepath + '/' + path
            wrapper = FileWrapper(open(filepath, 'rb'))
            response = HttpResponse(wrapper, content_type=mimetypes.guess_type(filepath)[0])
            response['Content-Length'] = os.path.getsize(filepath)
            response['Content-Disposition'] = 'attachment; filename=' + path.split('/')[-1]
            return response
        elif file_or_dir == 'dir':
            dirpath = self.basepath + '/' + path
            dirname = dirpath.split('/')[-2]
            response = HttpResponse(content_type='application/x-gzip')
            response['Content-Disposition'] = 'attachment; filename=%s.tar.gz' % unidecode(dirname)
            tarred = tarfile.open(fileobj=response, mode='w:gz')
            tarred.add(dirpath, arcname=dirname)
            tarred.close()
            return response

    def render(self, request, path):
        if 'download' in request.GET:
            return self.download(path, request.GET['download'])
        if path:
            return self.media(path)
        CKEditorFuncNum = request.GET.get('CKEditorFuncNum', '')
        self.current_path = '/'
        self.current_id = 1
        if request.method == 'POST':
            if self.is_admin_view:
                form = FileManagerForm(request.POST, request.FILES)
                if form.is_valid():
                    for message in self.handle_form(form, request.FILES):
                        messages.add_message(request, messages.WARNING, message)
            else:
                messages.add_message(request, messages.WARNING, _('You dont have a permissions to do this!'))
        if settings.FILEMANAGER_CHECK_SPACE:
            space_consumed = self.get_size(self.basepath)
        else:
            space_consumed = 0
        return render(request, 'filemanager/index.html', {
            'dir_structure': self.directory_structure(),
            'current_id': self.current_id,
            'CKEditorFuncNum': CKEditorFuncNum,
            'ckeditor_baseurl': self.ckeditor_baseurl,
            'public_url_base': self.public_url_base,
            'space_consumed': space_consumed,
            'max_space': self.maxspace,
            'show_space': settings.FILEMANAGER_SHOW_SPACE,
            'is_admin_view': self.is_admin_view,
        })
