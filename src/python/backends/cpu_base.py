"""Base functionality for both JIT and dynamic CPU backends."""

from __future__ import division

__copyright__ = "Copyright (C) 2007 Andreas Kloeckner"

__license__ = """
This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see U{http://www.gnu.org/licenses/}.
"""




import pymbolic.mapper
import hedge.optemplate
from pytools import memoize_method




class ExecutorBase(object):
    def __init__(self, discr):
        self.discr = discr

    def instrument(self):
        discr = self.discr
        if not discr.instrumented:
            return

        from hedge.tools import time_count_flop

        from hedge.tools import \
                diff_rst_flops, diff_rescale_one_flops, lift_flops, \
                mass_flops

        self.diff_rst = \
                time_count_flop(
                        self.diff_rst,
                        discr.diff_timer,
                        discr.diff_counter,
                        discr.diff_flop_counter,
                        diff_rst_flops(discr))

        self.diff_rst_to_xyz = \
                time_count_flop(
                        self.diff_rst_to_xyz,
                        discr.diff_timer,
                        discr.diff_counter,
                        discr.diff_flop_counter,
                        diff_rescale_one_flops(discr))

        self.do_mass = \
                time_count_flop(
                        self.do_mass,
                        discr.mass_timer,
                        discr.mass_counter,
                        discr.mass_flop_counter,
                        mass_flops(discr))

        self.lift_flux = \
                time_count_flop(
                        self.lift_flux,
                        discr.lift_timer,
                        discr.lift_counter,
                        discr.lift_flop_counter,
                        lift_flops(discr))

    def lift_flux(self, fgroup, matrix, scaling, field, out):
        from hedge._internal import lift_flux
        lift_flux(fgroup, matrix.astype(field.dtype), scaling, field, out)

    def diff_rst(self, op, rst_axis, field):
        result = self.discr.volume_zeros()

        from hedge.tools import make_vector_target
        target = make_vector_target(field, result)

        target.begin(len(self.discr), len(self.discr))

        from hedge._internal import perform_elwise_operator
        for eg in self.discr.element_groups:
            perform_elwise_operator(eg.ranges, eg.ranges, 
                    op.matrices(eg)[rst_axis].astype(field.dtype), target)

        target.finalize()

        return result

    def diff_rst_to_xyz(self, op, rst, result=None):
        from hedge.tools import make_vector_target
        from hedge._internal import perform_elwise_scale

        if result is None:
            result = self.discr.volume_zeros()

        for rst_axis in range(self.discr.dimensions):
            target = make_vector_target(rst[rst_axis], result)

            target.begin(len(self.discr), len(self.discr))
            for eg in self.discr.element_groups:
                perform_elwise_scale(eg.ranges,
                        op.coefficients(eg)[op.xyz_axis][rst_axis],
                        target)
            target.finalize()

        return result

    def diff_xyz(self, mapper, op, expr, field, result):
        rst_derivatives = mapper.diff_rst_with_cache(op, expr, field)

        from hedge.tools import make_vector_target
        from hedge._internal import perform_elwise_scale

        for rst_axis in range(self.discr.dimensions):
            target = make_vector_target(rst_derivatives[rst_axis], result)

            target.begin(len(self.discr), len(self.discr))
            for eg in self.discr.element_groups:
                perform_elwise_scale(eg.ranges,
                        op.coefficients(eg)[op.xyz_axis][rst_axis],
                        target)
            target.finalize()

        return result

    def do_mass(self, op, field, out):
        from hedge.tools import make_vector_target
        target = make_vector_target(field, out)

        target.begin(len(self.discr), len(self.discr))
        for eg in self.discr.element_groups:
            from hedge._internal import perform_elwise_scaled_operator
            perform_elwise_scaled_operator(eg.ranges, eg.ranges,
                   op.coefficients(eg), op.matrix(eg), 
                   target)
        target.finalize()



class ExecutionMapperBase(hedge.optemplate.Evaluator,
        hedge.optemplate.BoundOpMapperMixin, 
        hedge.optemplate.LocalOpReducerMixin):

    def __init__(self, context, discr, executor):
        hedge.optemplate.Evaluator.__init__(self, context)
        self.discr = discr
        self.executor = executor

        self.diff_rst_cache = {}

    def diff_rst_with_cache(self, op, expr, field):
        try:
            result = self.diff_rst_cache[op.__class__, expr]
        except KeyError:
            result = self.diff_rst_cache[op.__class__, expr] = \
                    [self.executor.diff_rst(op, i, field) 
                            for i in range(self.discr.dimensions)]

        return result

    def map_diff_base(self, op, field_expr, out=None):
        field = self.rec(field_expr)

        if out is None:
            out = self.discr.volume_zeros()
        self.executor.diff_xyz(self, op, field_expr, field, out)
        return out

    def map_mass_base(self, op, field_expr, out=None):
        field = self.rec(field_expr)

        if isinstance(field, (float, int)) and field == 0:
            return 0

        if out is None:
            out = self.discr.volume_zeros()

        self.executor.do_mass(op, field, out)

        return out

    def map_sumadfasdf(self, expr, out=None):
        if out is None:
            out = self.discr.volume_zeros()
        for child in expr.children:
            result = self.rec(child, out)
            if result is not out:
                out += result
        return out

    def map_constant(self, expr, out=None):
        return expr

    def map_subscript(self, expr, out=None):
        return hedge.optemplate.Evaluator.map_subscript(self, expr)

    def map_product(self, expr, out=None):
        return hedge.optemplate.Evaluator.map_product(self, expr)

    def map_quotient(self, expr, out=None):
        return hedge.optemplate.Evaluator.map_quotient(self, expr)

    def map_variable(self, expr, out=None):
        return hedge.optemplate.Evaluator.map_variable(self, expr)
