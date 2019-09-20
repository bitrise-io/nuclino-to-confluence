#!/usr/bin/env python3
"""
# --------------------------------------------------------------------------------------------------
# Import a Nuclino Workspace to Confluence
# --------------------------------------------------------------------------------------------------
# This script can be run in two modes plan and execute:
# - The plan mode traverses an exported Nuclino Workspace's folder and creates the "plan" subfolder
# - The execute mode traverses the "plan" folder and creates Pages accordingly in Confluence
#   then uploads the files as subpages
# --------------------------------------------------------------------------------------------------
# Usage: import.py spacekey folder command
# --------------------------------------------------------------------------------------------------
"""

from shutil import copy
import logging
import urllib
import sys
import os
import re
import argparse
import json
import codecs
import markdown
import requests


logging.basicConfig(level=logging.INFO, format='%(asctime)s - \
%(levelname)s - %(funcName)s [%(lineno)d] - \
%(message)s')
LOGGER = logging.getLogger(__name__)

# ArgumentParser to parse arguments and options
PARSER = argparse.ArgumentParser()
PARSER.add_argument('spacekey',
                    help="Confluence Space key for the page. If omitted, will use user space.")
PARSER.add_argument("folder", help="Path to the exported Nuclino Workspace")
PARSER.add_argument("command", help="The import command: plan or execute")
PARSER.add_argument('-u', '--username', help='Confluence username if $CONFLUENCE_USERNAME not set.')
PARSER.add_argument('-p', '--password', help='Confluence password if $CONFLUENCE_PASSWORD not set.')
PARSER.add_argument('-o', '--orgname',
                    help='Confluence organisation if $CONFLUENCE_ORGNAME not set. '
                         'e.g. https://XXX.atlassian.net/wiki'
                         'If orgname contains a dot, considered as the fully qualified domain name.'
                         'e.g. https://XXX')
PARSER.add_argument('-l', '--loglevel', default='INFO',
                    help='Use this option to set the log verbosity.')

ARGS = PARSER.parse_args()

# Assign global variables
try:
    # Set log level
    LOGGER.setLevel(getattr(logging, ARGS.loglevel.upper(), None))

    SPACE_KEY = ARGS.spacekey
    WORK_FOLDER = ARGS.folder
    IMPORT_COMMAND = ARGS.command
    USERNAME = os.getenv('CONFLUENCE_USERNAME', ARGS.username)
    PASSWORD = os.getenv('CONFLUENCE_PASSWORD', ARGS.password)
    ORGNAME = os.getenv('CONFLUENCE_ORGNAME', ARGS.orgname)


    if USERNAME is None:
        LOGGER.error('Error: Username not specified by environment variable or option.')
        sys.exit(1)

    if PASSWORD is None:
        LOGGER.error('Error: Password not specified by environment variable or option.')
        sys.exit(1)

    if not os.path.exists(WORK_FOLDER):
        LOGGER.error('Error: Path: %s does not exist.', WORK_FOLDER)
        sys.exit(1)

    if not os.path.isdir(WORK_FOLDER):
        LOGGER.error('Error: Path: %s is not a folder.', WORK_FOLDER)
        sys.exit(1)

    PLAN_FOLDER = os.path.join(WORK_FOLDER, "plan")

    if SPACE_KEY is None:
        SPACE_KEY = '~%s' % (USERNAME)

    if ORGNAME is not None:
        if ORGNAME.find('.') != -1:
            CONFLUENCE_API_URL = 'https://%s' % ORGNAME
        else:
            CONFLUENCE_API_URL = 'https://%s.atlassian.net/wiki' % ORGNAME
    else:
        LOGGER.error('Error: Org Name not specified by environment variable or option.')
        sys.exit(1)

except Exception as err:
    LOGGER.error('\n\nException caught:\n%s ', err)
    LOGGER.error('\nFailed to process command line arguments. Exiting.')
    sys.exit(1)

def get_space_base_id():
    """
    Gets the base page's ID of the Confluence Space

    :return:string
    """
    session = requests.Session()
    session.auth = (USERNAME, PASSWORD)
    session.headers.update({'Content-Type': 'application/json'})

    url = '%s/rest/api/space/%s' % (CONFLUENCE_API_URL, SPACE_KEY)

    response = session.get(url)
    try:
        response.raise_for_status()
    except requests.exceptions.HTTPError as excpt:
        LOGGER.error("error: %s - %s", excpt, response.content)
        exit(1)

    if response.status_code == 200:
        data = response.json()
        return data[u'_expandable'][u'homepage'][len("/rest/api/content/"):]
    LOGGER.error('Cannot get Space main page ID')
    LOGGER.error('Status: %s', response.status_code)
    LOGGER.error('Response: %s', response.content)
    sys.exit(1)

def check_plan_requirements():
    """
    Check if the index.md file can be found under WORKING_FOLDER
    Check if a previous plan was made
    Create the plan folder
    :return:
    """
    index_file = os.path.join(WORK_FOLDER, "index.md")

    if not os.path.isfile(index_file):
        LOGGER.error('Error: The index file of the Workspace cannot be found at %s', index_file)
        sys.exit(1)

    LOGGER.info('Workspace Index file found %s', index_file)

    if os.path.isdir(PLAN_FOLDER):
        LOGGER.error('Error: Previous plan detected under %s Remove the plan folder, and run the script again', PLAN_FOLDER)
        sys.exit(1)

    LOGGER.info("Creating plan folder...")
    os.makedirs(PLAN_FOLDER)

def is_index_file(file_path):
    """
    Check if file_path is an Index file

    :return:boolean
    """
    pattern = re.compile(r'^\* \[.*]\((.*)\)')
    try:
        with open(file_path) as index_file:
            for line in index_file:
                if not pattern.match(line):
                    return False
    except Exception as err:
        LOGGER.error('\n\nFailed to open file\n%s ', err)
        sys.exit(1)
    return True

def get_subfolder_name(file_name):
    """
    Removes the .md extension and replaces spaces with _ in file_name and returns it

    :return:string
    """
    if file_name.endswith('.md'):
        file_name = file_name[:-12]
    file_name = file_name.replace(" ", "_")
    return file_name

def process_index(file_path, file_name):
    """
    Process an index file by creating a subfolder for it (except for the root index.md)
    Then iterate over its entryes and either copy them to the folder created (the root plan folder in case of index.md)
    or recursivly call process_index on them if they are index files themselves

    :return:
    """
    LOGGER.info('Processing Index file %s ...', file_name)
    if file_path:
        LOGGER.info('Creating subfolder %s', file_path)
        os.makedirs(os.path.join(PLAN_FOLDER, file_path))
    try:
        with open(os.path.join(WORK_FOLDER, file_name)) as index_file:
            for line in index_file:
                md_file = os.path.join(WORK_FOLDER, re.search(r'^\* \[.*]\((.*)\)', line).group(1))
                if not os.path.isfile(md_file):
                    escaped_md_file = md_file.replace("\\", "")
                    if os.path.isfile(escaped_md_file):
                        md_file = escaped_md_file
                    else:
                        LOGGER.error('Error: Cannot find markdown file %s', md_file)
                        sys.exit(1)
                LOGGER.info('Markdown file found %s', md_file)
                if is_index_file(md_file):
                    process_index(
                        os.path.join(file_path, get_subfolder_name(os.path.basename(md_file))),
                        os.path.basename(md_file))
                else:
                    dest = os.path.join(PLAN_FOLDER, file_path)
                    LOGGER.info('Copying %s to %s', md_file, dest)
                    copy(md_file, dest)
    except Exception as err:
        LOGGER.error('\n\nFailed to open file\n%s ', err)
        sys.exit(1)

def plan_import():
    """
    Create plan folder and populate it with the markdown files

    :return:
    """
    check_plan_requirements()
    process_index("", "index.md")

def is_child(child, ancestor):
    """
    Determine if a page ID is a direct child of an ancestor ID

    :return:bool
    """
    session = requests.Session()
    session.auth = (USERNAME, PASSWORD)
    session.headers.update({'Content-Type': 'application/json'})

    url = '%s/rest/api/content/%s?expand=ancestors' % (CONFLUENCE_API_URL, child)

    response = session.get(url)
    try:
        response.raise_for_status()
    except requests.exceptions.HTTPError as excpt:
        LOGGER.error("error: %s - %s", excpt, response.content)
        return ""

    if response.status_code == 200:
        data = response.json()
        if data[u'ancestors'][len(data[u'ancestors'])-1][u'id'] == child:
            return True
    return False

def get_page_id(title, ancestor):
    """
    Gets the a page's ID by title

    :return:string
    """
    session = requests.Session()
    session.auth = (USERNAME, PASSWORD)
    session.headers.update({'Content-Type': 'application/json'})

    url = '%s/rest/api/content?title=%s&spaceKey=%s' % (CONFLUENCE_API_URL, urllib.parse.quote_plus(title), SPACE_KEY)

    response = session.get(url)
    try:
        response.raise_for_status()
    except requests.exceptions.HTTPError as excpt:
        LOGGER.error("error: %s - %s", excpt, response.content)
        return ""

    if response.status_code == 200:
        data = response.json()
        for res in data[u'results']:
            if is_child(res[u'id'], ancestor):
                return res[u'id']
        return ""

    LOGGER.error('Cannot get page ID by title: %s', title)
    LOGGER.error('Status: %s', response.status_code)
    LOGGER.error('Response: %s', response.content)
    return ""

def create_page(title, body, ancestor):
    """
    Create a new page

    :param title: confluence page title
    :param body: confluence page content
    :param ancestor: confluence page ancestor
    :return:string
    """

    existing_id = get_page_id(title, ancestor)
    if existing_id:
        LOGGER.info('Page already exists...')
        return existing_id

    LOGGER.info('Creating page...')
    LOGGER.info('Title: %s\nBody: %s\nAncestor: %s', title, body, ancestor)

    url = '%s/rest/api/content/' % CONFLUENCE_API_URL

    session = requests.Session()
    session.auth = (USERNAME, PASSWORD)
    session.headers.update({'Content-Type': 'application/json'})

    ancestors = [{'type': 'page', 'id': ancestor}]

    new_page = {'type': 'page',
                'title': title,
                'space': {'key': SPACE_KEY},
                'body': {
                    'storage': {
                        'value': body,
                        'representation': 'storage'
                    }
                },
                'ancestors': ancestors,
               }

    LOGGER.info("data: %s", json.dumps(new_page))

    response = session.post(url, data=json.dumps(new_page))
    try:
        response.raise_for_status()
    except requests.exceptions.HTTPError as excpt:
        LOGGER.error("error: %s - %s", excpt, response.content)
        exit(1)

    if response.status_code == 200:
        data = response.json()
        space_name = data[u'space'][u'name']
        page_id = data[u'id']
        link = '%s%s' % (CONFLUENCE_API_URL, data[u'_links'][u'webui'])

        LOGGER.info('Page created in %s with ID: %s.', space_name, page_id)
        LOGGER.info('URL: %s', link)
        return page_id

    LOGGER.error('Could not create page.')
    LOGGER.info('Response Status:\n%s', response.status_code)
    LOGGER.info('Response Body:\n%s', response.content)
    sys.exit(1)

def upper_chars(string, indices):
    """
    Make characters uppercase in string

    :param string: string to modify
    :param indices: character indice to change to uppercase
    :return: uppercased string
    """
    upper_string = "".join(c.upper() if i in indices else c for i, c in enumerate(string))
    return upper_string

def strip_type(tag, tagtype):
    """
    Strips Note or Warning tags from html in various formats

    :param tag: tag name
    :param tagtype: tag type
    :return: modified tag
    """
    tag = re.sub(r'%s:\s' % tagtype, '', tag.strip(), re.IGNORECASE)
    tag = re.sub(r'%s\s:\s' % tagtype, '', tag.strip(), re.IGNORECASE)
    tag = re.sub(r'<.*?>%s:\s<.*?>' % tagtype, '', tag, re.IGNORECASE)
    tag = re.sub(r'<.*?>%s\s:\s<.*?>' % tagtype, '', tag, re.IGNORECASE)
    tag = re.sub(r'<(em|strong)>%s:<.*?>\s' % tagtype, '', tag, re.IGNORECASE)
    tag = re.sub(r'<(em|strong)>%s\s:<.*?>\s' % tagtype, '', tag, re.IGNORECASE)
    tag = re.sub(r'<(em|strong)>%s<.*?>:\s' % tagtype, '', tag, re.IGNORECASE)
    tag = re.sub(r'<(em|strong)>%s\s<.*?>:\s' % tagtype, '', tag, re.IGNORECASE)
    string_start = re.search('<.*?>', tag)
    tag = upper_chars(tag, [string_start.end()])
    return tag

def convert_doctoc(html):
    """
    Convert doctoc to confluence macro

    :param html: html string
    :return: modified html string
    """

    toc_tag = '''<p>
    <ac:structured-macro ac:name="toc">
      <ac:parameter ac:name="printable">true</ac:parameter>
      <ac:parameter ac:name="style">disc</ac:parameter>
      <ac:parameter ac:name="maxLevel">7</ac:parameter>
      <ac:parameter ac:name="minLevel">1</ac:parameter>
      <ac:parameter ac:name="type">list</ac:parameter>
      <ac:parameter ac:name="outline">clear</ac:parameter>
      <ac:parameter ac:name="include">.*</ac:parameter>
    </ac:structured-macro>
    </p>'''

    html = re.sub(r'\<\!\-\- START doctoc.*END doctoc \-\-\>', toc_tag, html, flags=re.DOTALL)

    return html

def convert_info_macros(html):
    """
    Converts html for info, note or warning macros

    :param html: html string
    :return: modified html string
    """
    info_tag = '<p><ac:structured-macro ac:name="info"><ac:rich-text-body><p>'
    note_tag = info_tag.replace('info', 'note')
    warning_tag = info_tag.replace('info', 'warning')
    close_tag = '</p></ac:rich-text-body></ac:structured-macro></p>'

    # Custom tags converted into macros
    html = html.replace('<p>~?', info_tag).replace('?~</p>', close_tag)
    html = html.replace('<p>~!', note_tag).replace('!~</p>', close_tag)
    html = html.replace('<p>~%', warning_tag).replace('%~</p>', close_tag)

    # Convert block quotes into macros
    quotes = re.findall('<blockquote>(.*?)</blockquote>', html, re.DOTALL)
    if quotes:
        for quote in quotes:
            note = re.search('^<.*>Note', quote.strip(), re.IGNORECASE)
            warning = re.search('^<.*>Warning', quote.strip(), re.IGNORECASE)

            if note:
                clean_tag = strip_type(quote, 'Note')
                macro_tag = clean_tag.replace('<p>', note_tag).replace('</p>', close_tag).strip()
            elif warning:
                clean_tag = strip_type(quote, 'Warning')
                macro_tag = clean_tag.replace('<p>', warning_tag).replace('</p>', close_tag).strip()
            else:
                macro_tag = quote.replace('<p>', info_tag).replace('</p>', close_tag).strip()

            html = html.replace('<blockquote>%s</blockquote>' % quote, macro_tag)

    # Convert doctoc to toc confluence macro
    html = convert_doctoc(html)

    return html

def convert_comment_block(html):
    """
    Convert markdown code bloc to Confluence hidden comment

    :param html: string
    :return: modified html string
    """
    open_tag = '<ac:placeholder>'
    close_tag = '</ac:placeholder>'

    html = html.replace('<!--', open_tag).replace('-->', close_tag)

    return html

def convert_code_block(html):
    """
    Convert html code blocks to Confluence macros

    :param html: string
    :return: modified html string
    """
    code_blocks = re.findall(r'<pre><code.*?>.*?</code></pre>', html, re.DOTALL)
    if code_blocks:
        for tag in code_blocks:

            conf_ml = '<ac:structured-macro ac:name="code">'
            conf_ml = conf_ml + '<ac:parameter ac:name="theme">Midnight</ac:parameter>'
            conf_ml = conf_ml + '<ac:parameter ac:name="linenumbers">true</ac:parameter>'

            lang = re.search('code class="(.*)"', tag)
            if lang:
                lang = lang.group(1)
            else:
                lang = 'none'

            conf_ml = conf_ml + '<ac:parameter ac:name="language">' + lang + '</ac:parameter>'
            content = re.search(r'<pre><code.*?>(.*?)</code></pre>', tag, re.DOTALL).group(1)
            content = '<ac:plain-text-body><![CDATA[' + content + ']]></ac:plain-text-body>'
            conf_ml = conf_ml + content + '</ac:structured-macro>'
            conf_ml = conf_ml.replace('&lt;', '<').replace('&gt;', '>')
            conf_ml = conf_ml.replace('&quot;', '"').replace('&amp;', '&')

            html = html.replace(tag, conf_ml)

    return html

def process_refs(html):
    """
    Process references

    :param html: html string
    :return: modified html string
    """
    refs = re.findall(r'\n(\[\^(\d)\].*)|<p>(\[\^(\d)\].*)', html)

    if refs:

        for ref in refs:
            if ref[0]:
                full_ref = ref[0].replace('</p>', '').replace('<p>', '')
                ref_id = ref[1]
            else:
                full_ref = ref[2]
                ref_id = ref[3]

            full_ref = full_ref.replace('</p>', '').replace('<p>', '')
            html = html.replace(full_ref, '')
            href = re.search('href="(.*?)"', full_ref).group(1)

            superscript = '<a id="test" href="%s"><sup>%s</sup></a>' % (href, ref_id)
            html = html.replace('[^%s]' % ref_id, superscript)

    return html

def get_body(file_path):
    """
    get the body of a markdown file as html

    :return:string
    """
    with codecs.open(file_path, 'r', 'utf-8') as mdfile:
        html = markdown.markdown(mdfile.read(), extensions=['markdown.extensions.tables', 'markdown.extensions.fenced_code'])
    html = convert_info_macros(html)
    html = convert_comment_block(html)
    html = convert_code_block(html)
    html = process_refs(html)
    return html

def execute_import():
    """
    Traverses the plan folder and creates Confluence pages accordingly

    :return:
    """

    confluence_pages = {}

    base_id = get_space_base_id()

    for paths, dirs, files in os.walk(PLAN_FOLDER):
        page_path = paths.split(PLAN_FOLDER)[1]
        elems = page_path.split("/")[1:]
        ancestor_id = confluence_pages["/" + "/".join(elems[:-1])]["page_id"] if len(elems) > 1 else base_id
        page_id = base_id
        if page_path:
            page_id = create_page(elems[len(elems) - 1], "", ancestor_id)
            confluence_pages[page_path] = {"page_id": page_id}
        for md_file in files:
            body = get_body(os.path.join(WORK_FOLDER, md_file))
            file_name = md_file[:-12]
            create_page(file_name, body, page_id)

def main():
    """
    Main program

    :return:
    """

    if IMPORT_COMMAND not in ["plan", "execute"]:
        LOGGER.error('Error: Invalid command %s The command must be: plan or execute', IMPORT_COMMAND)
        sys.exit(1)

    if IMPORT_COMMAND == "plan":
        plan_import()
    else:
        execute_import()

    LOGGER.info('Confluence Import %s completed successfully.', "Planning" if IMPORT_COMMAND == "plan" else "Execution")

if __name__ == "__main__":
    main()
