# Copyright 2021 MONAI Consortium
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import glob
import os
from datetime import datetime
from typing import List

import pydicom
from app.inference import DetectionResult, DetectionResultList
from pydicom.uid import generate_uid

import monai.deploy.core as md
from monai.deploy.core import DataPath, ExecutionContext, InputContext, IOType, Operator, OutputContext
from monai.deploy.core.domain.dicom_series_selection import StudySelectedSeries


@md.input("original_dicom", List[StudySelectedSeries], IOType.IN_MEMORY)
@md.input("detection_predictions", DetectionResultList, IOType.IN_MEMORY)
@md.output("gsps_files", DataPath, IOType.DISK)
class GenerateGSPSOp(Operator):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def generate_gsps(self, image_ds: pydicom.Dataset, detection_list: List[DetectionResult]) -> pydicom.Dataset:

        slice_coords = [inst.first_pixel_on_slice_normal for inst in image_ds]

        gsps_ds: pydicom.Dataset = pydicom.Dataset()
        gsps_ds.add_new(0x00080016, 'UI', '1.2.840.10008.5.1.4.1.1.11.1')  # SOPClassUID ==  GSPS
        gsps_ds.add_new(0x0020000D, 'UI', image_ds[0x0020000D].value)  # StudyInstanceUID
        gsps_ds.add_new(0x0020000E, 'UI', image_ds[0x0020000E].value)  # SeriesInstanceUID
        gsps_ds.add_new(0x00080018, 'UI', generate_uid())  # SOP Instance UID

        gsps_ds.add_new(0x0010020, 'LO', image_ds[0x00100020].value)  # PatientId
        gsps_ds.add_new(0x00100010, 'PN', image_ds[0x00100010].value)  # PatientName
        gsps_ds.add_new(0x00100030, 'DA', image_ds[0x00100030].value)  # PatientBirthdate
        gsps_ds.add_new(0x00100040, 'CS', image_ds[0x00100040].value)  # PatientSex

        gsps_ds.add_new(0x00080020, 'DA', image_ds[0x00080020].value)  # StudyDate
        gsps_ds.add_new(0x00080030, 'TM', image_ds[0x00080030].value)  # StudyTime
        gsps_ds.add_new(0x00080050, 'SH', image_ds[0x00080050].value)  # AccessionNumber
        gsps_ds.add_new(0x00080090, 'PN', image_ds[0x00080090].value)  # PhysicianName
        gsps_ds.add_new(0x00200010, 'SH', image_ds[0x00200010].value)  # StudyID
        gsps_ds.add_new(0x00200011, 'IS', image_ds[0x00200011].value)  # SeriesNumber

        gsps_ds.add_new(0x00080060, 'CS', image_ds[0x00080060].value)  # Modality
        gsps_ds.add_new(0x00080070, 'LO', 'MONAI')  # Manufacturer

        gsps_ds.add_new(0x00700082, 'DA', datetime.utcnow().strftime("%Y%m%d"))  # PresentationCreationDate
        gsps_ds.add_new(0x00700083, 'TM', datetime.utcnow().strftime("%Y%m%d"))  # PresentationCreationTime

        gsps_ds.add_new(0x00081115, 'SQ', series)  # ReferencedSeriesSequence

        series: pydicom.Dataset = pydicom.Dataset()
        series.add_new(0x0020000E, 'UI', image_ds[0x0020000E].value)  # SeriesInstanceUID
        series.add_new(0x00081140, 'SQ', image_ds)  # ReferencedImageSequence

        for detection in detection_list:

            affected_slice_idx = [idx for idx, val in enumerate(slice_coords) if val >= detection[3] and val <= detection[4]]

            # add geometric annotations from detector findings
            displayedArea: pydicom.Dataset = pydicom.Dataset()
            displayedArea.add_new(0x00700052, 'SL', f"{detection[0]}\\{detection[1]}")  # DisplayedAreaTopLeftHandCorner
            displayedArea.add_new(0x00700053, 'SL', f"{detection[2]}\\{detection[3]}")  # DisplayedAreaBottomRightHandCorner
            displayedArea.add_new(0x00700100, 'CS', "TRUE SIZE")  # PresentationSizeMode

        gsps_ds.add_new(0x0070005A, 'SQ', displayedArea)

        gsps_ds.add_new(0x00282000, 'OB', b'\x00\x00\x00\x01')  # ICCProfile

    def compute(self, op_input: InputContext, op_output: OutputContext, context: ExecutionContext):

        selected_study = op_input.get("original_dicom")[0]
        detection_result: DetectionResultList = op_input.get("detection_predictions")
        output_path = op_output.get("gsps_files").path

        for series, detections in zip(selected_study.selected_series, detection_result.detection_list):
            gsps_ds = self.generate_gsps(series.series, detections)

            pydicom.dcmwrite(output_path, gsps_ds)
