'''
header.py: functions to extract identifiers from dicom headers

Copyright (c) 2017 Vanessa Sochat

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
'''


from deid.logger import bot
from deid.utils import (
    read_json
)

from .tags import blank_tag

from deid.identifiers.utils import (
    create_lookup
)

from deid.config import load_deid

from pydicom import read_file
from pydicom.errors import InvalidDicomError
import dateutil.parser
import tempfile

from .utils import (
    get_func, 
    perform_addition,
    perform_action,
    get_item_timestamp,
    get_entity_timestamp
)

import os

here = os.path.dirname(os.path.abspath(__file__))


######################################################################
# MAIN GET FUNCTIONS
######################################################################

def get_fields(dicom,skip=None):
    '''get fields is a simple function to extract a dictionary of fields
    (non empty) from a dicom file.
    '''    
    if skip is None:
        skip = []

    fields = dict()
    contenders = dicom.dir()
    dicom_file = os.path.basename(dicom.filename)
    for contender in contenders:
        if contender in skip:
            continue
        value = dicom.get(contender)
        if value not in [None,""]:
            fields[contender] = value
    bot.debug("Found %s defined fields for %s" %(len(fields),
                                                 dicom_file))
    return fields



def get_identifiers(dicom_files,force=True,config=None,
                                entity_id=None,item_id=None):
    '''extract all identifiers from a dicom image.
    This function cannot be sure if more than one source_id 
    is present in the data, so it returns a lookup dictionary 
    by patient and item id.
    :param dicom_files: the dicom file(s) to extract from
    :param force: force reading the file (default True)
    :param config: if None, uses default in provided module folder
    :param entity_id: if specified, override default in config
    :param item_id: if specified, overrides 
    '''

    if config is None:
        config = "%s/config.json" %(here)

    if not os.path.exists(config):
        bot.error("Cannot find config %s, exiting" %(config))

    config = read_json(config)['get']

    if not isinstance(dicom_files,list):
        dicom_files = [dicom_files]

    ids = dict() # identifiers

    # We will skip PixelData
    skip = config['skip']

    # Organize the data based on the following
    if entity_id is None:
        entity_id = config['ids']['entity']
    if item_id is None:
        item_id = config['ids']['item']


    for dicom_file in dicom_files:

        dicom = read_file(dicom_file,force=True)

        # Read in / calculate preferred values
        entity = dicom.get(entity_id)
        item = dicom.get(item_id)

        bot.debug('entity id: %s' %(entity))
        bot.debug('item id: %s' %(item))

        if entity is None or item is None:
            bot.warning("Cannot find entity or item id for %s, skipping." %(dicom_file))
            continue

        if entity not in ids:
            ids[entity] = dict()
         
        ids[entity][item] = get_fields(dicom,skip=skip)
        
    return ids



def replace_identifiers(dicom_files,
                        ids=None,
                        deid=None,
                        overwrite=False,
                        entity_id=None,
                        item_id=None,
                        force=True,
                        config=None):

    '''replace identifiers will replace dicom_files with data from ids based
    on a combination of a config (default is blank all) and a users preferences (deid)
    :param ids: the ids from get_identifiers, with any changes
    :param dicom_files: the dicom file(s) to extract from
    :param force: force reading the file (default True)
    :param config: if None, uses default in provided module folder
    :param overwrite: if False, save updated files to temporary directory
    '''
    if overwrite is False:
        save_base = tempfile.mkdtemp()

    if config is None:
        config = "%s/config.json" %(here)

    if deid is not None:
        deid = load_deid(deid)

    if not os.path.exists(config):
        bot.error("Cannot find config %s, exiting" %(config))

    config = read_json(config)

    if not isinstance(dicom_files,list):
        dicom_files = [dicom_files]

    # Organize the data based on the following
    if entity_id is None:
        entity_id = config['get']['ids']['entity']
    if item_id is None:
        item_id = config['get']['ids']['item']
    

    # Parse through dicom files, update headers, and save
    updated_files = []

    for dicom_file in dicom_files:

        dicom = read_file(dicom_file,force=True)
        dicom_name = os.path.basename(dicom_file)

        # Read in / calculate preferred values
        entity = dicom.get(entity_id)
        item = dicom.get(item_id)
        fields = dicom.dir()

        bot.debug('entity id: %s' %(entity))
        bot.debug('item id: %s' %(item))

        # Is the entity_id in the data structure given to de-identify?
        if ids is not None:
            if entity in ids:

                items = ids[entity]
                if item in items:
                
                    # First preference goes to user specified options
                    if deid is not None:
                        if deid['format'] == 'dicom':
                            for action in deid['header']:

                                 # We've dealt with this field
                                 fields = [x for x in fields if x != action['field']]
                                 dicom = perform_action(dicom=dicom,
                                                        item=items[item],
                                                        action=action)

        else:

            # Next perform actions in default config, only if not done
            for action in config['put']['actions']:
                if action['field'] in fields:
                     fields = [x for x in fields if x != action['field']]
                     dicom = perform_action(dicom=dicom,
                                            item=items[item],
                                            action=action)

            # Additions
            for action in config['put']['additions']:
                if action['name'] in fields:
                     fields = [x for x in fields if x != action['name']]
                     dicom = perform_addition(config,dicom)

            # Blank remaining fields
            for field in fields:
                dicom = blank_tag(dicom,field)

            
        # Save to file
        output_dicom = dicom_file
        if overwrite is False:
            output_dicom = "%s/%s" %(save_base,os.path.basename(dicom_file))
        dicom.save_as(output_dicom)

        updated_files.append(output_dicom)
       

    return updated_files