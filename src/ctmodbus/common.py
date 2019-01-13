def csr(glob, step=1, min=0, max=0):
    """Returns a dictionary of tuples that can be used with range()"""
    results = {}
    for glob in addr_globs:
        addr_glob = glob.split('-')
        if len(addr_glob) == 1:
            try:
                addr = int(addr_glob[0])
                if addr > 65535:
                    return False
                response = event.app.session.read_coils(addr, 1, unit=1)
                results[addr] = int(response.bits[0])
            except:
                output_text += str(response) + '\n'
                return output_text
        elif len(addr_glob) == 2:
            try:
                addr1, addr2 = [int(x) for x in addr_glob]
                if addr1 > 65535 or addr2 > 65535:
                    return False
                addr2 += 1
                count = addr2 - addr1
                step = 10
                for i in range(0, count, step):
                    response = event.app.session.read_coils(addr1+i, min(step, count-i), unit=1)
                    for address, result in zip(range(addr1+i, addr1+i+min(step, count-i)), response.bits):
                        results[address] = int(result)
            except:
                output_text += str(response) + '\n'
                return output_text
