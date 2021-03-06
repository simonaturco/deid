---
title: 4. Cleaning Pixels
category: Getting Started
order: 6
---

At this point, you've possibly obtained identifiers via a [get]({{ site.baseurl }}/getting-started/dicom-get) 
action, and you want to figure out which of your images have pixels burned 
into the data. If you don't want the detalis, jump into our 
[example script](https://github.com/pydicom/deid/blob/master/examples/dicom/pixels/run-cleaner-client.py). 
Here we will walk through how this cleaner was derived, and how it works.

 - [Inspiration from CTP](#inspiration-from-ctp)
 - [Deid Implementation](#deid-implementation)
 - [Client](#client) to control the cleaning process
 - [Detect](#detect) areas in the image likely to need cleaning
 - [Clean and Save](#clean-and-save)
 - [Debugging](#debugging) and other important notes

<a id="inspiration-from-ctp">
## Inspiration from CTP

Flagging images with potentially having burned in PHI is based on a well established 
rule-based approach. We know a concrete list of header fields and known locations 
with PHI associated with fields in the header, and we can check these fields in any
files and then perform cleaning if there is a match. This approach is based on the 
MIRCTP functions to [filter DICOM](http://mircwiki.rsna.org/index.php?title=The_CTP_DICOM_Filter) 
and then [Anonymize](http://mircwiki.rsna.org/index.php?title=The_CTP_DICOM_Pixel_Anonymizer). 
The  [DicomPixelAnonymizer.script](https://github.com/johnperry/CTP/blob/master/source/files/scripts/DicomPixelAnonymizer.script) 
is a rule based list of known machine and modality types, and specific locations 
in the pixels where annotations are commonly found. The 
[BurnedInPixels.script](https://github.com/johnperry/CTP/blob/master/source/files/scripts/BurnedInPixelsFilter.script) 
is a set of filters that, given that an image passes through them, it continues processing. 
If it fails, then we flag it. If we look at the script above, we see the following:

```
    # We continue processing given that:
    # ![0008,0008].contains("SAVE") *   ImageType doesn't contain save AND
    # [0018,1012].equals("") *          DateofSecondaryCapture flat not present AND
    # ![0008,103e].contains("SAVE") *   SeriesDescription does not contain save AND
    # [0018,1016].equals("") *          SecondaryDeviceCaptureManufacturer flag not present AND
    # [0018,1018].equals("") *          SecondaryDeviceCaptureManufacturerModelName flag not present AND
    # [0018,1019].equals("") *          SecondaryDeviceCaptureDeviceSoftwareVersion flag not present AND
    # ![0028,0301].contains("YES")      BurnedInAnnotation is not YES
```

and I've provided a "human friendly" translation of the rules. The `!` operator indicates a `not`, 
and the `*` indicates `and`. You can imagine an image passing through those tests, and if it 
makes it all the way through, it's considered ok. If any of the tests fail, then it 
gets flagged for PHI (Burned Annotations) and is quarantined. Thus, we can read 
through the dicom fields and summarize the above as:

We continue processing given that:
 - Image was not saved with some secondary software or device
 - Image is not flagged to have burned pixels

If we look at the [DicomPixelAnonymizer.script](https://github.com/johnperry/CTP/blob/master/source/files/scripts/DicomPixelAnonymizer.script), 
it also contains criteria (and additionally, locations) for pixel areas that are known/likely 
to have annotations. The general format looks like this:

```
{ signature }
(region) (region) ... (region)
```
and the signature looks similar to an expression used in the `BurnedInPixels.script`, 
but the difference is that groups of logic are then paired with one or more regions:

```
{ Modality.equals("CT") 
    * Manufacturer.containsIgnoreCase("manufacturer1") 
        * ManufacturerModelName.containsIgnoreCase("modelA") }
(0,0,100,20) (480,200,32,250)
```

The expression above would say: 

The pixels with bounding boxes (0,0,100,20) and (480,200,32,250) should be removed if:
   - the modality is CT AND
   - the Manufacterer contains text "manufacturer1" (and ignore the case) AND
   - the Manufacturer model name text contains "modelA" (and ignore the case)


I'm not entirely sure why these two are separate (as both seem to indicate a flag 
for an image having PHI) but likely it's because the first group (`BurnedInPixels.script`) 
indicates header fields that are likely to indicate annotation, but don't 
carry any obvious mapping to a location. We can think of both as a set of filters, 
some with a clear location, and others not. TLDR: the second file (`DicomPixelAnonymizer.script`) 
has both header fields and locations.

<a id="deid-implementation">
## Deid Implementation

We have a set of pixel functions that mirror the functionality of MIRCTP, 
and we take a similar approach of deriving the rules for this process from a 
deid recipe. Our implementeation of a [DicomCleaner](https://github.com/pydicom/deid/blob/master/deid/dicom/pixels/clean.py#L35) generally works as follows:

 1. The user initializes a [Recipe](recipe.md) to configure detecting images with PHI (and possibly cleaning). The recipe has two parts - a set of filters to run over the headers to estimate if an image has burned in pixels (a section that starts with `%filter`), and a list of header cleaning rules (`%header`).
 2. The recipe is used to categorize the images into groups based on the defined lists, or to clean the data.
 3. The user selects some subset of images to continue forward with replacement of identifiers.

To jump right in to using the Dicom Cleaner, see our [example script](https://github.com/pydicom/deid/blob/master/examples/dicom/pixels/run-cleaner-client.py). 
We will walk through the basics here.

We start by importing the class


```python
from deid.dicom import DicomCleaner, get_files 
from deid.data import get_dataset
```

and grabbing a dicom file to work with

```python
dataset = get_dataset('dicom-cookies')
dicom_file = list(get_files(dataset))[0]
```

<a id="client">
### Client

We need to instantiate a client once, and can use this client to clean one or more files.
Note that there are various options for setting default output folders. if you don't set
an output folder, a temporary directory is created and used.


```python
client = DicomCleaner()
client = DicomCleaner(output_folder='/home/vanessa/Desktop')
```

The basic steps we will take are the following:

 - `client.detect(dicom_file)`: detect if the image potentially has burned in pixels
 - `client.clean()`: clean the areas by writing black pixels, given that coordinates are provided in the recipe.
 - `client.save_<format>`: save the images to a new dicom or png

### Coordinates from Fields

By default, we use a list of rules provided by CTP and other users in [dicom.deid](https://github.com/pydicom/deid/blob/master/deid/data/deid.dicom), and these are based on finding known locations based on dicom header values.
If you want to define a custom cleaning action, for example, taking the coordinates
defined based on the [SequenceOfUltrasoundRegions](http://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_C.8.5.5.html#table_C.8-17) identifier, you can define this as a `CLEAN` action in any
of the provided lists. An instruction to identify a known region in this file looks like this:

```
LABEL LightSpeed Dose Report # (Susan Weber)
  contains ManufacturerModelName LightSpeed VCT
  + contains Modality CT
  + contains ImageType SCREEN SAVE || contains SeriesDescription Dose
  coordinates 0,0,512,121
```

And so to identify an instruction to clean based on presence of a particular
dicom header (and then use the pixels identified within) would look like this:

```
LABEL Clean Ultrasound
    present SequenceOfUltrasoundRegions
    coordinates from:SequenceOfUltrasoundRegions
```

In the above, we tell deid to look for the dicom header `SequenceOfUltrasoundRegions`
(it must be present), and given this condition, we look for coordinates
from that field. This action is added to the default deid.dicom recipe, so if we
just create a cleaner and interact with a dicom file that has this field, we should
see the coordinates extracted. For example, here is an ultrasound image that
has regions defined until this field:

```python
from deid.dicom import DicomCleaner
client = DicomCleaner()
client.detect('echo1.dcm')
{'flagged': True,
 'results': [{'reason': ' SequenceOfUltrasoundRegions present ',
   'group': 'graylist',
   'coordinates': ['231,70,784,657']},
  {'reason': 'and ImageType contains RECONSTRUCTION|SECONDARY|DERIVED',
   'group': 'graylist',
   'coordinates': []},
  {'reason': 'and ImageType contains DERIVED|SECONDARY|SCREEN SAVE|VOLREN|VXTL STATE',
   'group': 'graylist',
   'coordinates': []},
  {'reason': 'and ImageType contains DERIVED|SECONDARY|SCREEN|SAVE',
   'group': 'blacklist',
   'coordinates': []}]}
```

Notice that the coordinates are filled in. We might next want to perform a clean.

```python
client.clean()

import os
client.save_dicom(output_folder=os.getcwd())                                                    
'/home/vanessa/Desktop/Code/deid/echo/cleaned-echo1.dcm'
```

<a id="detect">
### Detect

Detect means using the deid recipe to parse headers. You must run detect before you try to clean. If you don't:

```python
client.clean()
WARNING Use <deid.dicom.pixels.clean.DicomCleaner object at 0x7fafb70b9cf8>.detect() to find coordinates first.
```

Once you've run detect, you will get a result that includes any flags triggered:

```python
client.detect(dicom_file)

{'flagged': True,
'results': [{'coordinates': [],
  'group': 'blacklist',
  'reason': ' ImageType missing  or ImageType empty '}]}
```

<a id="clean-and-save">
### Clean and Save
After detection, the flags that were triggered are saved with the client, until 
you override with another file. You can now run clean, and save the 
images to a format that you like. Remember that even with flags, if there are no coordinates 
associated with the flag, no changes are done to the image.

```python
client.clean()
client.save_png()
client.save_dicom()
```

If you need to specify a different header for pixel data (default is `PixelData`)
but you might choose also `FloatPixelData` or `DoubleFloatPixelData` you can do:

```python
client.clean(pixel_data_attribute="FloatPixelData")
```

<a id="debugging">
### Debugging and Important Notes

In a recent pull request we [encountered](https://github.com/pydicom/deid/pull/134) 
an issue where a user had decompressed the data without changing the `dicom.PixelInterpretation`,
which is a header that tells pydicom how to read the data. The suggested approach
when you do `dicom.decompress()` is to set `dicom.PhotometricInterpreation = 'RGB'` 
after doing so:

```python
dicom.decompress()
dicom.PhotometricInterpreation = 'RGB'
```

If you see this warning message:

```python
ValueError: The length of the pixel data in the dataset (312907680 bytes) doesn't match the expected length (208605120 bytes). The dataset may be corrupted or there may be an issue with the pixel data handler.
```

you likely have an issue. Although deid will attempt to fix it for you, this isn't a guarantee
that the fix is correct, and behavior might be changed in future versions of
pydicom to raise an error. To disable the fix, you can do:

```python
client.clean(fix_interpretation=False)
```

Please [see the note](https://pydicom.github.io/pydicom/stable/old/image_data_handlers.html#usage)
on the pydicom documentation for more details. Also, it would be useful to use machine 
learning to detect text. if you want to develop this or have ideas, please reach out.

