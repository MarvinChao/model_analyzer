# Copyright (C) 2019-2022 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

import csv
import logging as log
import os
from typing import List, Tuple
import pandas as pd
import numpy

from model_analyzer.layer_provider import LayerTypesManager, LayerType, Constant, Result, Parameter
from model_analyzer.model_metadata import ModelMetaData
from model_analyzer.model_type_analyzer import ModelTypeGuesser
from model_analyzer.value_converter import ValueConverter


# pylint: disable=too-many-instance-attributes
class ModelComputationalComplexity:
    def __init__(self, metadata: ModelMetaData):
        self._model_metadata = metadata
        self._layer_providers = [LayerTypesManager.provider(layer) for layer in self._model_metadata.ops]
        self._ignored_layers = []
        self._ignore_unknown_layers = True
        self._computational_complexity = {}
        net_precisions = set()
        for layer_provider in self._layer_providers:
            for i in range(layer_provider.get_outputs_number()):
                net_precisions.add(layer_provider.get_output_precision(i))
            self._computational_complexity[layer_provider.name] = {
                'layer_type': layer_provider.type,
                'layer_name': layer_provider.name
            }

            input_blob, output_blob = self.get_blob_sizes(layer_provider)
            input_dims, output_dims = self.get_blob_dims(layer_provider)
            input_vol, output_vol = self.get_blob_volumes(layer_provider)
            input_precision, output_precision = self.get_blob_precisions(layer_provider)
            self._computational_complexity[layer_provider.name]['input_blob'] = input_blob
            self._computational_complexity[layer_provider.name]['output_blob'] = output_blob
            self._computational_complexity[layer_provider.name]['input_dims'] = input_dims
            self._computational_complexity[layer_provider.name]['output_dims'] = output_dims
            self._computational_complexity[layer_provider.name]['input_vols'] = input_vol
            self._computational_complexity[layer_provider.name]['output_vols'] = output_vol
            self._computational_complexity[layer_provider.name]['input_precision'] = input_precision
            self._computational_complexity[layer_provider.name]['output_precision'] = output_precision

        self._executable_precisions = list(net_precisions.union(self._model_metadata.int8precisions))
        self._params_const_layers = set()

    @property
    def _output_names(self) -> Tuple[str]:
        return tuple(
            layer_provider.name
            for layer_provider in self._layer_providers
            if isinstance(layer_provider, Result)
        )

    @property
    def _input_names(self) -> Tuple[str]:
        return tuple(
            layer_provider.name
            for layer_provider in self._layer_providers
            if isinstance(layer_provider, Parameter)
        )

    @property
    def executable_precisions(self):
        return self._executable_precisions

    @property
    def model(self):
        return self._model_metadata.model

    def get_total_params(self) -> dict:
        parameters = {
            'total_params': 0,
            'zero_params': 0
        }
        for layer_provider in self._layer_providers:
            params = 0
            layer_computational_complexity = self._computational_complexity[layer_provider.name]
            layer_computational_complexity['m_params'] = 0.0

            layer_params_dict = layer_provider.get_params()
            if not layer_params_dict:
                continue

            for const_name in layer_params_dict:
                params, zeros = layer_params_dict[const_name]
                # Avoid double counting
                if const_name in self._params_const_layers:
                    continue
                parameters['total_params'] += params
                self._params_const_layers.add(const_name)
                if layer_provider.name in self._ignored_layers:
                    continue
                parameters['zero_params'] += zeros
            self._computational_complexity[layer_provider.name]['m_params'] = ValueConverter.to_giga(params)
        return parameters


    @staticmethod
    def get_blob_sizes_and_precisions(layer_provider) -> tuple:
        inputs = []
        for i in range(layer_provider.get_inputs_number()):
            input_precision = layer_provider.get_input_precision(i)
            input_shape_as_string = 'x'.join(map(str, layer_provider.get_input_shape(i)))
            input_str = f'{input_precision}({input_shape_as_string})'
            inputs.append(input_str)
        in_blob = ' '.join(inputs)

        outputs = []
        for i in range(layer_provider.get_outputs_number()):
            output_precision = layer_provider.get_output_precision(i)
            output_shape_as_string = 'x'.join(map(str, layer_provider.get_output_shape(i)))
            output_str = f'{output_precision}({output_shape_as_string})'
            outputs.append(output_str)
        out_blob = ' '.join(outputs)

        return in_blob, out_blob

    def get_blob_sizes(self, layer_provider) -> tuple:
        inputs = []
        for i in range(layer_provider.get_inputs_number()):
            input_shape_as_string = 'x'.join(map(str, layer_provider.get_input_shape(i)))
            input_str = f'{input_shape_as_string}'
            inputs.append(input_str)
        in_blob = ' '.join(inputs)
            
        outputs = []
        for i in range(layer_provider.get_outputs_number()):
            output_shape_as_string = 'x'.join(map(str, layer_provider.get_output_shape(i)))
            output_str = f'{output_shape_as_string}'
            outputs.append(output_str)
        out_blob = ' '.join(outputs)
            
        return in_blob, out_blob

    def get_blob_dims(self, layer_provider) -> tuple:
        inputs = []
        for i in range(layer_provider.get_inputs_number()):
            inputs.append(layer_provider.get_input_shape(i))

        outputs = []
        for i in range(layer_provider.get_outputs_number()):
            outputs.append(layer_provider.get_output_shape(i))

        return inputs, outputs

    def get_blob_volumes(self, layer_provider) -> tuple:
        iVol = []
        for i in range(layer_provider.get_inputs_number()):
            iVol.append(numpy.prod(numpy.absolute(layer_provider.get_input_shape(i))))

        oVol = []
        for i in range(layer_provider.get_outputs_number()):
            oVol.append(numpy.prod(numpy.absolute(layer_provider.get_output_shape(i))))

        return iVol, oVol

    def get_blob_precisions(self, layer_provider) -> tuple:
        inputs = []
        for i in range(layer_provider.get_inputs_number()):
            input_precision = layer_provider.get_input_precision(i)
            input_str = f'{input_precision}'
            inputs.append(input_str)
        in_precision = ' '.join(inputs)
        
        outputs = []
        for i in range(layer_provider.get_outputs_number()):
            output_precision = layer_provider.get_output_precision(i)
            output_str = f'{output_precision}'
            outputs.append(output_str)
        out_precision = ' '.join(outputs)
        
        return in_precision, out_precision

    def get_maximum_memory_consumption(self) -> int:
        total_memory_size = 0
        for layer_provider in self._layer_providers:
            if not isinstance(layer_provider, Constant):
                total_memory_size += layer_provider.get_output_blobs_total_size()
        return total_memory_size

    def get_minimum_memory_consumption(self) -> int:
        input__layer_providers = list(filter(lambda x: x.name in self._input_names, self._layer_providers))
        all_layer_providers = list(
            filter(lambda x: not isinstance(x, Constant), self._layer_providers))
        is_computed = {layer_provider.name: False for layer_provider in all_layer_providers}

        direct_input_children_names = []
        for layer_provider in input__layer_providers:
            direct_input_children_names.extend(layer_provider.get_child_names())

        max_memory_size = 0
        for layer_provider in all_layer_providers:
            current_memory_size = layer_provider.get_output_blobs_total_size()

            for prev_layer_provider in all_layer_providers:
                if prev_layer_provider.name == layer_provider.name:
                    break
                memory_not_needed = True

                for child_name in prev_layer_provider.get_child_names():
                    memory_not_needed = memory_not_needed and is_computed.get(child_name)

                if not memory_not_needed:
                    current_memory_size += prev_layer_provider.get_output_blobs_total_size()

            max_memory_size = max(max_memory_size, current_memory_size)

            is_computed[layer_provider.name] = True
        return max_memory_size

    def print_network_info(self, output, file_name, complexity, complexity_filename):
        g_flops, g_iops = self.get_total_ops()

        parameters = self.get_total_params()
        total_parameters = parameters['total_params']
        zero_params = parameters['zero_params']

        total_params = total_parameters / 1000000.0
        sparsity = zero_params / total_parameters * 100
        min_mem_consumption = self.get_minimum_memory_consumption() / 1000000.0
        max_mem_consumption = self.get_maximum_memory_consumption() / 1000000.0
        net_precisions = (
            self._executable_precisions.pop()
            if len(self._executable_precisions) == 1 else
            f'MIXED ({"-".join(sorted(self._executable_precisions))})'
        )
        log.info('GFLOPs: %.6f', g_flops)
        log.info('GIOPs: %.6f', g_iops)
        log.info('MParams: %.6f', total_params)
        log.info('Sparsity: %.6f%%', sparsity)
        log.info('Minimum memory consumption (MB): %.6f', min_mem_consumption)
        log.info('Maximum memory consumption (MB): %.6f', max_mem_consumption)
        export_network_into_xlsx(g_flops, g_iops, total_params, sparsity, min_mem_consumption, max_mem_consumption,
                                net_precisions, output, file_name)
        if complexity:
            self.export_layers_into_xlsx(output, complexity_filename)

    def export_layers_into_csv(self, output_dir: str, file_name: str):
        if output_dir:
            file_name = os.path.join(output_dir, file_name)
        with open(file_name, mode='w') as info_file:
            info_writer = csv.writer(info_file, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)
            info_writer.writerow(
                ['LayerType', 'LayerName', 'GFLOPs', 'GIOPs', 'MParams', 'LayerParams', 'InputBlobs', 'OutputBlobs', 'InputPrecision', 'OutputPrecision']
            )
            layers_ids = self._model_metadata.ops_ids
            try:
                sorted_layers = sorted(self._computational_complexity.keys(), key=lambda x: layers_ids[x])
            except (KeyError, TypeError):
                sorted_layers = sorted(self._computational_complexity.keys())
            core_layers = filter(lambda x: x not in self._input_names, sorted_layers)
            for layer_name in core_layers:
                cur_layer = self._computational_complexity[layer_name]
                if cur_layer['m_params'] == 0:
                    continue
                info_writer.writerow([
                    cur_layer['layer_type'],
                    cur_layer['layer_name'],
                    '{:.6f}'.format(float(cur_layer['g_flops'])),
                    '{:.6f}'.format(float(cur_layer['g_iops'])),
                    '{:.6f}'.format(float(cur_layer['m_params'])),
                    cur_layer.get('layer_params'),
                    cur_layer['input_blob'],
                    cur_layer['output_blob'],
                    cur_layer['input_precision'],
                    cur_layer['output_precision'],
                ])
        log.info('Complexity file name: %s', file_name)

    def export_layers_into_xlsx(self, output_dir: str, file_name: str):
        if output_dir:
            file_name = os.path.join(output_dir, file_name)

        layers_ids = self._model_metadata.ops_ids
        try:
            sorted_layers = sorted(self._computational_complexity.keys(), key=lambda x: layers_ids[x])
        except (KeyError, TypeError):
            sorted_layers = sorted(self._computational_complexity.keys())
        core_layers = filter(lambda x: x not in self._input_names, sorted_layers)

        Layers_DF = pd.DataFrame()
        for layer_name in core_layers:
            cur_layer = self._computational_complexity[layer_name]
            if cur_layer['m_params'] == 0:
                continue
            cur_layer_info = [
                    cur_layer['layer_type'],
                    cur_layer['layer_name'],
                    cur_layer['input_dims'],
                    cur_layer['output_dims'],
                    int(cur_layer['g_flops'] * 1000000000),
                    int(cur_layer['g_iops'] * 1000000000),
                    int(cur_layer['m_params'] * 1000000),
                    cur_layer.get('layer_params'),
                    sum(cur_layer['input_vols']),
                    sum(cur_layer['output_vols']),
                    cur_layer['input_precision'],
                    cur_layer['output_precision'],
                ]
            if Layers_DF.index.empty:
                Layers_DF = pd.DataFrame(cur_layer_info).transpose()
            else:
                Layers_DF.loc[len(Layers_DF.index)] = cur_layer_info

            writer = pd.ExcelWriter(file_name, engine='xlsxwriter')
            Layers_DF.to_excel(writer, sheet_name='Summary', startrow=0, header=['LayerType', 'LayerName', 'Input Dimensions','Output Dimensions','FLOPs', 'IOPs', 'Params', 'LayerParams', 'Input Volumes', 'Output Volumes', 'InputPrecision', 'OutputPrecision'], index=False)

        # Improve Spreadsheet cosmetics
        Layer_WS = writer.sheets['Summary']
        Layer_WS.set_column(0, 9, 20)

        writer.close()

    def get_ops(self, layer_provider: LayerType) -> int:
        try:
            total_flops = layer_provider.get_ops() * pow(10, -9)
        except NotImplementedError as error:
            self._computational_complexity[layer_provider.name]['g_iops'] = 0
            self._computational_complexity[layer_provider.name]['g_flops'] = 0
#            self._computational_complexity[layer_provider.name]['g_iops'] = -1
#            self._computational_complexity[layer_provider.name]['g_flops'] = -1
            raise error
        self._computational_complexity[layer_provider.name]['layer_params'] = get_layer_params(layer_provider)
        self._computational_complexity[layer_provider.name]['g_iops'] = (
            total_flops if layer_provider.name in self._model_metadata.int8layers else 0
        )
        self._computational_complexity[layer_provider.name]['g_flops'] = (
            0 if layer_provider.name in self._model_metadata.int8layers else total_flops
        )
        return total_flops

    def get_total_ops(self) -> tuple:
        uncounted_layers = set()
        unknown_layers = set()
        total_flops = 0
        total_iops = 0
        for layer_provider in self._layer_providers:
            if layer_provider.__class__ == LayerType:
                unknown_layers.add(layer_provider.type)
            try:
                layer_flops = self.get_ops(layer_provider)
            except NotImplementedError:
                uncounted_layers.add(layer_provider.type)
                continue
            if layer_provider.name in self._model_metadata.int8layers:
                total_iops += layer_flops
                continue
            total_flops += layer_flops
        if not self._ignore_unknown_layers and unknown_layers:
            print(f'Unknown types: {", ".join(unknown_layers)}')
            raise Exception('Model contains unknown layers!')
        if uncounted_layers:
            print(f'Warning, GOPS for layer(s) was not counted: - {", ".join(uncounted_layers)}')
        return total_flops, total_iops

    def set_ignored_layers(self, _ignored_layers: List[str], ignore_first_conv: bool, ignore_fc: bool):
        self._ignored_layers.extend(_ignored_layers)
        all_convs = []
        for layer_provider in self._layer_providers:
            if layer_provider.type.lower() == 'convolution':
                all_convs.append(layer_provider.name)
            elif layer_provider.type.lower() == 'fullyconnected' and ignore_fc:
                self._ignored_layers.append(layer_provider.name)
            elif layer_provider.type.lower() == 'scaleshift':
                self._ignored_layers.extend(layer_provider.name)
        if ignore_first_conv:
            self._ignored_layers.append(all_convs[0])

    def set_ignore_unknown_layers(self, _ignore_unknown_layers: bool):
        self._ignore_unknown_layers = _ignore_unknown_layers


# pylint: disable=too-many-arguments
def export_network_into_csv(g_flops, g_iops, total_params, sparsity, min_mem_consumption, max_mem_consumption,
                            net_precisions, output_dir, file_name):
    if output_dir:
        file_name = os.path.join(output_dir, file_name)
    with open(file_name, mode='w') as info_file:
        info_writer = csv.writer(info_file, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)
        info_writer.writerow(
            ['GFLOPs', 'GIOPs', 'MParams', 'MinMem', 'MaxMem', 'Sparsity', 'Precision']
        )
        info_writer.writerow(
            [
                f'{g_flops:.4f}', f'{g_iops:.4f}', f'{total_params:.4f}', f'{min_mem_consumption:.4f}',
                f'{max_mem_consumption:.4f}', f'{sparsity:.4f}', net_precisions
            ]
        )
    log.info('File name with network status information : %s', file_name)

def export_network_into_xlsx(g_flops, g_iops, total_params, sparsity, min_mem_consumption, max_mem_consumption,
                                    net_precisions, output_dir, file_name):
    if output_dir:
        file_name = os.path.join(output_dir, file_name)

    Network_Info = [
                f'{g_flops:.4f}', f'{g_iops:.4f}', f'{total_params:.4f}', f'{min_mem_consumption:.4f}',
                f'{max_mem_consumption:.4f}', f'{sparsity:.4f}', net_precisions
            ]
    Network_DF = pd.DataFrame(Network_Info).transpose()
    writer = pd.ExcelWriter(file_name, engine='xlsxwriter')
    Network_DF.to_excel(writer, sheet_name='Summary', startrow=0, header=['GFLOPs', 'GIOPs', 'MParams', 'MinMem', 'MaxMem', 'Sparsity', 'Precision'], index=False)
    # Improve Spreadsheet cosmetics
    Network_WS = writer.sheets['Summary']
    Network_WS.set_column(0, 6, 20)

    writer.close()

def get_layer_params(layer_provider: LayerType) -> str:
    params = []

    layer_params = layer_provider.params
    layer_params.pop('element_type', None)
    layer_params.pop('shape', None)

    if not layer_params:
        return ''

    for param in sorted(layer_params):
        value = layer_params[param]
        if isinstance(value, list):
            value_string = f'({"xs".join(str(x) for x in value)})'
        elif isinstance(value, str) and ',' in value:
            value_string = f'({"x".join(value.split(","))})'
        else:
            value_string = value

        params.append(f'{param}: {value_string}')
    return f'[{"; ".join(params)}]'
