import requests
import numpy as np
from curses.ascii import isalpha, isdigit
from scipy.spatial import ConvexHull

def get_stoich_reduced_list_from_prototype(prototype_label):
    """
    Get numerical list of stoichiometry from prototype label, i.e. "AB3\_...." -> [1,3]

    Args:
        prototype_label:
            AFLOW prototype label

    Returns:
        List of reduced stoichiometric numbers
    """                        
    stoich_reduced_formula = prototype_label.split("_")[0]
    stoich_reduced_list=[]
    stoich_reduced_curr = None
    for char in stoich_reduced_formula:
        if isalpha(char):
            if stoich_reduced_curr is not None:
                if stoich_reduced_curr == 0:
                    stoich_reduced_curr = 1
                stoich_reduced_list.append(stoich_reduced_curr)
            stoich_reduced_curr = 0
        else:
            assert isdigit(char)                            
            stoich_reduced_curr*=10 # will throw an error if we haven't encountered an alphabetical letter, good
            stoich_reduced_curr+=int(char)
    # write final number                    
    if stoich_reduced_curr == 0:
        stoich_reduced_curr = 1
    stoich_reduced_list.append(stoich_reduced_curr)    
    return stoich_reduced_list

def get_formation_energies(species_list,model=None):
    """
    Query OpenKIM repository for test results or reference data for constructing a thermodynamic hull.
    Args:
        species_list:
            List of all species to query for. Every result or data containing any combination of one or more of these will be returned
        model:
            OpenKIM model to query for. If this is None, reference data are queried for instead

    Returns:
        * (N, len(species_list)) ndarray representing N points to build the hull out of. The last column is the energy, the others are the molar fractions of each element in species_list except the first
        * N-length list of prototype labels
        * len(species_list)-length list of indices into the previous two outputs indicating the elemental reference for each 
    """
    assert len(species_list)>1
    assert len(set(species_list))==len(species_list)
    if model==None:
        model_query=''
        meta_type='rd'
    else:
        model_query='"meta.subject.extended-id":"%s",'%model
        meta_type='tr'
    result = requests.post("https://query.openkim.org/api",data={'query': '{"meta.type":"%s",%s"property-id":"tag:staff@noreply.openkim.org,2023-02-21:property/binding-energy-crystal","stoichiometric-species.source-value":{"$not":{"$elemMatch":{"$nin":%s}}}}'%(meta_type,model_query,str(species_list).replace("'",'"')), 'fields': '{"prototype-label.source-value":1,"stoichiometric-species.source-value":1,"binding-potential-energy-per-formula.source-value":1}', 'database': 'data'}).json()
    # initialize dict for elemental references
    elemental_references = []
    reference_indices = []
    for species in species_list:
        elemental_references.append(0.)
        reference_indices.append(-1)
    
    for i,entry in enumerate(result):
        species=entry["stoichiometric-species"]["source-value"]
        if len(species)==1:
            energy = entry["binding-potential-energy-per-formula"]["source-value"]
            species = species[0]
            species_index=species_list.index(species)
            if energy < elemental_references[species_index]:
                elemental_references[species_index] = energy
                reference_indices[species_list.index(species)] = i
    #now build the hull list of dicts
    prototype_labels=[]
    hull_pts = np.ndarray((len(result),len(species_list)))
    for i,entry in enumerate(result):
        prototype_label = entry["prototype-label"]["source-value"]
        prototype_labels.append(prototype_label)
        curr_species_list = entry["stoichiometric-species"]["source-value"]        
        stoich_reduced_list = get_stoich_reduced_list_from_prototype(prototype_label)
        stoich_reduced_list_full = np.zeros(len(species_list))
        for (element,stoich_num) in zip(curr_species_list,stoich_reduced_list):
            stoich_reduced_list_full[species_list.index(element)]=stoich_num
        #set the coordinates to the stoichiometry, skipping first element
        num_atoms_in_formula = sum(stoich_reduced_list_full)
        hull_pts[i,:-1]=[elem_num/num_atoms_in_formula for elem_num in stoich_reduced_list_full][1:]
        hull_pts[i,-1]=(entry["binding-potential-energy-per-formula"]["source-value"]-np.dot(elemental_references,stoich_reduced_list_full))/num_atoms_in_formula

    return hull_pts,prototype_labels,reference_indices

def get_2d_lower_hull(species_list,model=None):
    """
    Build 2d lower hull from OpenKim query
    Args:
        species_list:
            List of all species to query for. Every result or data containing any combination of one or more of these will be returned
        model:
            OpenKIM model to query for. If this is None, reference data are queried for instead

    Returns:
        * (N, len(species_list)) ndarray representing N points the hull was built from. The last column is the energy, the others are the molar fractions of each element in species_list except the first
        * N-length list of prototype labels
        * list of indices corresponding to points constituting the lower hull
    """
    hull_pts,prototype_labels,reference_indices=get_formation_energies(species_list,model)

    hull = ConvexHull(hull_pts)

    #In 2D, ConvexHull.vertices are guaranteed to be CCW. So we just need to go from reference_indices[0] to [1], possibly wrapping around

    lower_hull_vertices = [reference_indices[0]]
    i = list(hull.vertices).index(reference_indices[0])
    while hull.vertices[i] != reference_indices[1]:
        i = (i+1)%len(hull.vertices)
        lower_hull_vertices.append(hull.vertices[i])

    return hull_pts, prototype_labels, lower_hull_vertices