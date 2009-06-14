# Hedge - the Hybrid'n'Easy DG Environment
# Copyright (C) 2007 Andreas Kloeckner
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.




from __future__ import division
from pytools.test import mark_test




def run_convergence_test_advec(debug_output=False):
    """Test whether 2/3D advection actually converges"""

    import numpy
    import numpy.linalg as la
    from hedge.mesh import make_ball_mesh, make_box_mesh, make_rect_mesh
    from hedge.element import TetrahedralElement, TriangularElement
    from hedge.timestep import RK4TimeStepper
    from hedge.tools import EOCRecorder
    from math import sin, pi, sqrt
    from hedge.pde import StrongAdvectionOperator
    from hedge.data import TimeDependentGivenFunction
    from hedge.backends import guess_run_context
    from hedge.visualization import SiloVisualizer

    rcon = guess_run_context(disable=set(["cuda"]))

    # note: x component must remain zero because x-periodicity is used
    v = numpy.array([0.0,0.9,0.3])

    def f(x):
        return sin(x)

    def u_analytic(x, el, t):
        return f((numpy.dot(-v[:dims],x)/la.norm(v[:dims])+t*la.norm(v[:dims])))

    def boundary_tagger(vertices, el, face_nr, points):
        face_normal = el.face_normals[face_nr]
        if numpy.dot(face_normal, v[:len(face_normal)]) < 0:
            return ["inflow"]
        else:
            return ["outflow"]

    for i_mesh, mesh in enumerate([
        # 2D semiperiodic
        make_rect_mesh(b=(2*pi,3), max_area=0.4,
            periodicity=(True, False),
            subdivisions=(5,10),
            boundary_tagger=boundary_tagger, 
            ),
        # 3D x-periodic
        make_box_mesh((0,0,0), (2*pi, 2, 2), max_volume=0.4,
            periodicity=(True, False, False),
            boundary_tagger=boundary_tagger, 
            ),
        # non-periodic
        make_ball_mesh(r=pi, 
            boundary_tagger=boundary_tagger, max_volume=0.7),
        ]):
        for flux_type in StrongAdvectionOperator.flux_types:
            for random_partition in [True, False]:
                eoc_rec = EOCRecorder()

                if random_partition:
                    # Distribute elements randomly across nodes.
                    # This is bad, efficiency-wise, but it puts stress
                    # on the parallel implementation, which is desired here.
                    # Another main point of this is to force the code to split
                    # a periodic face pair across nodes.
                    from random import choice
                    partition = [choice(rcon.ranks) for el in mesh.elements]
                else:
                    partition = None

                for order in [1,2,3,4]:
                    if rcon.is_head_rank:
                        mesh_data = rcon.distribute_mesh(mesh, partition)
                    else:
                        mesh_data = rcon.receive_mesh()

                    dims = mesh.points.shape[1]
                    if dims == 2:
                        el_class = TriangularElement
                    else:
                        el_class = TetrahedralElement

                    discr = rcon.make_discretization(mesh_data, 
                            el_class(order))

                    op = StrongAdvectionOperator(v[:dims], 
                            inflow_u=TimeDependentGivenFunction(u_analytic),
                            flux_type=flux_type)
                    if debug_output:
                        vis = SiloVisualizer(discr, rcon)

                    u = discr.interpolate_volume_function(lambda x, el: u_analytic(x, el, 0))
                    ic = u.copy()

                    dt = discr.dt_factor(op.max_eigenvalue())
                    nsteps = int(1/dt)
                    if debug_output and rcon.is_head_rank:
                        print "#steps=%d #elements=%d" % (nsteps, len(mesh.elements))

                    test_name = "test-%s-o%d-m%d-r%s" % (
                            flux_type, order, i_mesh, random_partition)

                    rhs = op.bind(discr)

                    stepper = RK4TimeStepper()
                    for step in range(nsteps):
                        u = stepper(u, step*dt, dt, rhs)

                    u_true = discr.interpolate_volume_function(
                            lambda x, el: u_analytic(x, el, nsteps*dt))
                    error = u-u_true
                    l2_error = discr.norm(error)

                    if debug_output:
                        visf = vis.make_file(test_name+"-final")
                        vis.add_data(visf, [
                            ("u", u),
                            ("u_true", u_true),
                            ("ic", ic)])
                        visf.close()

                    eoc_rec.add_data_point(order, l2_error)

                if debug_output and rcon.is_head_rank:
                    print "%s\n%s\n" % (flux_type.upper(), "-" * len(flux_type))
                    print eoc_rec.pretty_print(abscissa_label="Poly. Order", 
                            error_label="L2 Error")

                assert eoc_rec.estimate_order_of_convergence()[0,1] > 3
                assert eoc_rec.estimate_order_of_convergence(2)[-1,1] > 7




@mark_test(mpi=True, long=True)
def test_hedge_parallel():
    import py.test
    import boostmpi

    from hedge_test_util import run_with_mpi_ranks
    run_with_mpi_ranks(__file__, 2, run_convergence_test_advec)




if __name__ == "__main__":
    test_hedge_parallel()
